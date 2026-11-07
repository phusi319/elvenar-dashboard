#!/usr/bin/env python3
"""
Audit script for elvenar_debug_dump_live_2026-11-07T09-10-02-944Z.json
"""
import os
import sys
import json
from collections import defaultdict

DUMP_PATH = r"D:\ElvenarAuto\Batte AI Data\elvenar_debug_dump_live_2026-11-07T09-10-02-944Z.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)
import benchmark_dump as bd

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    print("=" * 80)
    print("AUDITING NEW DUMP:", os.path.basename(DUMP_PATH))
    print("=" * 80)
    
    with open(DUMP_PATH, "r", encoding="utf-8") as f:
        dump = json.load(f)

    print(f"Total raw dump items: {len(dump)}")

    # Search for all interesting classes / service calls
    encounters = []
    tourney_encs = []
    battles = []
    effects_packets = []
    battle_services = []
    battle_unit_types = {}

    for idx, item in enumerate(dump):
        ts = item.get("timestamp") or item.get("time") or idx
        url = item.get("url") or ""
        payload = item.get("payload") or item.get("data")
        if not payload:
            continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue

        def walk(d):
            if isinstance(d, dict):
                cls_name = d.get("__class__")
                req_cls = d.get("requestClass")
                req_meth = d.get("requestMethod")

                if cls_name == "TournamentProvinceEncountersVO":
                    tourney_encs.append((ts, d))
                elif cls_name == "EncounterVO":
                    encounters.append((ts, d))
                elif cls_name == "InstantBattleResultVO":
                    battles.append((ts, d))
                elif cls_name == "BattleUnitTypeVO":
                    uid = d.get("id") or d.get("unitTypeId")
                    if uid:
                        battle_unit_types[uid] = d

                if req_cls == "EffectsService" and req_meth == "update":
                    effects_packets.append((ts, d.get("responseData")))
                if req_cls in ("BattleService", "BattlefieldService"):
                    battle_services.append((ts, req_cls, req_meth, d))

                for v in d.values():
                    walk(v)
            elif isinstance(d, list):
                for x in d:
                    walk(x)

        walk(payload)

    print(f"Found TournamentProvinceEncountersVO: {len(tourney_encs)}")
    print(f"Found EncounterVO: {len(encounters)}")
    print(f"Found InstantBattleResultVO (actual battles): {len(battles)}")
    print(f"Found EffectsService.update packets: {len(effects_packets)}")
    print(f"Found Battle/Battlefield service calls: {len(battle_services)}")
    print(f"Found BattleUnitTypeVOs: {len(battle_unit_types)}")

    # 1. Inspect TournamentProvinceEncountersVO
    print("\n" + "=" * 80)
    print("1. TOURNAMENT PROVINCE ENCOUNTERS INVENTORY")
    print("=" * 80)
    for idx, (ts, tpe) in enumerate(tourney_encs):
        p_sq = tpe.get("playerSquadSize")
        good = tpe.get("good_id")
        encs = tpe.get("encounters", [])
        print(f"--- Tourney Enc {idx} (ts={ts}, good={good}, p_sq={p_sq}): {len(encs)} sub-encounters")
        for sub_idx, se in enumerate(encs):
            waves = se.get("enemyWaves", [])
            for w_idx, wave in enumerate(waves):
                e_sq = wave.get("squadSize")
                army = wave.get("army", [])
                army_str = " / ".join(f"{u.get('unitTypeId')}(x{u.get('size')})" for u in army)
                print(f"    Sub-enc {sub_idx} Wave {w_idx}: e_sq={e_sq} | Army: {army_str}")

    # 2. Inspect InstantBattleResultVO (actual battles fought)
    print("\n" + "=" * 80)
    print("2. ACTUAL BATTLES FOUGHT (InstantBattleResultVO) vs SIMULATOR & ENGINE")
    print("=" * 80)
    city_atk = {'light_melee': 0.73, 'light_ranged': 0.89, 'mage': 0.90, 'heavy_melee': 0.83, 'heavy_ranged': 0.60}
    player_tiers = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 2, 2]

    for b_idx, (ts, bvo) in enumerate(battles):
        st = bvo.get("state", {})
        winner = st.get("winnerBit")
        units_order = st.get("unitsOrder", [])
        p_units = sorted([u for u in units_order if u.get("teamFlag") == 1], key=lambda u: bd.Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))
        e_units = sorted([u for u in units_order if u.get("teamFlag") == 2], key=lambda u: bd.Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))

        p_sq = int(sum(u.get("startAmountOfUnits", 0) * u.get("unitType", {}).get("unitWeight", 1) for u in p_units) / 5) if p_units else 0
        e_sq = int(sum(u.get("startAmountOfUnits", 0) * u.get("unitType", {}).get("unitWeight", 1) for u in e_units) / 5) if e_units else 0
        buffs = {'hp': p_units[0]['startHitpoints'] / p_units[0]['unitType']['hitpoints'] - 1, 'atk': city_atk}

        p_lineup = [u.get("unitType", {}).get("unitTypeId") for u in p_units]
        e_lineup = [u.get("unitType", {}).get("unitTypeId") for u in e_units]

        p_surv_real = []
        tot_lost = 0
        for u in p_units:
            start_cnt = u.get("startAmountOfUnits", 0)
            end_cnt = u.get("amountOfUnits", 0) or 0
            wt = u.get("unitType", {}).get("unitWeight", 1)
            tot_lost += (start_cnt - end_cnt) * wt
            surv_pct = (end_cnt / start_cnt * 100.0) if start_cnt > 0 else 0.0
            p_surv_real.append(f"S{bd.Y_TO_SLOT.get(u.get('startpos',{}).get('y',0),99)}:{surv_pct:.0f}%")

        actual_loss_pct = (tot_lost / (p_sq * 5) * 100.0) if p_sq > 0 else 0.0

        # Run actual lineup through simulator
        actual_sim = bd.simulate_battle(p_lineup, e_lineup, p_sq, e_sq, buffs, player_tiers)
        p_surv_sim = []
        for s in range(5):
            u_res = bd.resolve_unit(p_lineup[s], player_tiers)
            wt = u_res.get("wt", 1)
            full_cnt = max(1, int(p_sq / wt))
            end_cnt = actual_sim["end_counts"][s]
            surv_pct = (end_cnt / full_cnt * 100.0) if full_cnt > 0 else 0.0
            p_surv_sim.append(f"S{s+1}:{surv_pct:.0f}%")

        # Run engine recommendation for this battle
        rec_slots = bd.recommend_v70(e_lineup, buffs, player_tiers, p_sq, e_sq)
        l1 = [s[0][1] for s in rec_slots]
        l2 = [s[1][1] for s in rec_slots]
        sim_l1 = bd.simulate_battle(l1, e_lineup, p_sq, e_sq, buffs, player_tiers)
        sim_l2 = bd.simulate_battle(l2, e_lineup, p_sq, e_sq, buffs, player_tiers)

        p_names = " / ".join(f"{bd.resolve_unit(u)['short']}" for u in p_lineup)
        e_names = " / ".join(f"{bd.resolve_unit(u)['short']}" for u in e_lineup)
        l1_names = " / ".join(f"{bd.resolve_unit(u)['short']}" for u in l1)
        l2_names = " / ".join(f"{bd.resolve_unit(u)['short']}" for u in l2)

        print(f"\n[Battle {b_idx + 1}] (ts={ts}, winnerBit={winner})")
        print(f"  Enemy Lineup  ({e_sq}): {e_names} ({e_lineup})")
        print(f"  Actual Player Lineup ({p_sq}): {p_names} ({p_lineup})")
        print(f"  Actual Real Result: Loss = {actual_loss_pct:.1f}% | Per-slot surv: {', '.join(p_surv_real)}")
        print(f"  Actual Sim  Result: Loss = {actual_sim['loss_pct']:.1f}% (Won: {actual_sim['won']}) | Per-slot surv: {', '.join(p_surv_sim)}")
        diff_pts = actual_real_loss_pct = abs(actual_loss_pct - actual_sim['loss_pct'])
        print(f"  Simulator Error (|Real - Sim|): {diff_pts:.1f} pts")
        print(f"  Engine Rec #1: {l1_names} => Loss: {sim_l1['loss_pct']:.1f}% (Won: {sim_l1['won']})")
        print(f"  Engine Rec #2: {l2_names} => Loss: {sim_l2['loss_pct']:.1f}% (Won: {sim_l2['won']})")
        used_rec1 = (p_lineup == l1)
        used_rec2 = (p_lineup == l2)
        print(f"  Player Used: {'Lineup #1 Exactly' if used_rec1 else ('Lineup #2 Exactly' if used_rec2 else 'Custom Player Choice')}")

    # 3. Check Battle/Battlefield service calls
    print("\n" + "=" * 80)
    print("3. BATTLE/BATTLEFIELD SERVICE CALLS")
    print("=" * 80)
    for ts, req_cls, req_meth, d in battle_services:
        print(f"Service Call: {req_cls}.{req_meth} (ts={ts})")
        print(f"  Keys: {list(d.keys())}")
        if "obstacles" in str(d):
            print("  Contains 'obstacles' keyword!")

    # 4. Check EffectsService.update
    print("\n" + "=" * 80)
    print("4. EFFECTS SERVICE UPDATE (MILITARY BUFFS)")
    print("=" * 80)
    if effects_packets:
        ef_list = effects_packets[-1][1]
        print(f"Latest Effects packet has {len(ef_list)} effects")
        for ef in ef_list:
            cid = ef.get("confId")
            if cid in (711, 712, 713, 714, 715, 2043, 2045, 5016, 5019, 5002, 2123, 2103, 2082, 2112):
                print(f"  Military Effect: confId={cid}, actionId={ef.get('actionId')}, level={ef.get('level')}, stage={ef.get('stage')}, owner={ef.get('owner')}, type={ef.get('type')}")

    # 5. Inspect BattleUnitTypeVOs for mc_hr, eb_hr, tg_hr, mob_tglr
    print("\n" + "=" * 80)
    print("5. BATTLE UNIT TYPES IN GAME DUMP")
    print("=" * 80)
    check_uids = ["mc_hr_1", "mc_hr_2", "mc_hr_3", "eb_hr_3", "tg_hr_3", "mob_tglr_1", "mob_tglr_2", "mob_tglr_3"]
    for uid in check_uids:
        vo = battle_unit_types.get(uid)
        if vo:
            print(f"\nUnit: {uid} ({vo.get('name', '')})")
            print(f"  Class: {vo.get('unitClass')} | SubClass: {vo.get('unitSubClass')}")
            print(f"  HP: {vo.get('hitpoints')} | Dmg: {vo.get('damage')} | Init: {vo.get('initiative')} | Rng: {vo.get('range')} | Mv: {vo.get('movementRange')} | Wt: {vo.get('unitWeight')}")
            print(f"  Damage Bonuses: {vo.get('damageBonus')}")
            print(f"  Defense Bonuses: {vo.get('defenseBonus')}")
            print(f"  Abilities: {vo.get('abilities')}")
        else:
            print(f"\nUnit: {uid} NOT FOUND in dump!")

    # 6. Deep analysis of Enc 4 (the last viewed encounter)
    print("\n" + "=" * 80)
    print("6. DEEP ANALYSIS OF LAST ENCOUNTER VIEWED (Tourney Enc 4)")
    print("=" * 80)
    buffs = {'hp': 0.775, 'atk': {'light_melee': 0.73, 'light_ranged': 0.89, 'mage': 0.90, 'heavy_melee': 0.83, 'heavy_ranged': 0.60}}
    player_tiers = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 2, 2]
    p_sq = 25000
    e_sq = 51095
    wave = ['mob_hbma_3', 'mob_tghm_3', 'mob_eblr_3', 'mob_eblr_3', 'mob_tglr_3']

    # Stage 1 Heuristic scores
    heuristic_slots = bd.recommend_heuristic(wave, buffs, player_tiers, p_sq, e_sq)
    for s in range(5):
        target_name = bd.resolve_unit(wave[s])["short"]
        print(f"\nSlot {s+1} facing {wave[s]} ({target_name}):")
        for c in heuristic_slots[s][:6]:
            print(f"   {c[1]:10} ({c[2]:15}): score={c[0]:.2f}")

    # recommend_v70 output
    slots = bd.recommend_v70(wave, buffs, player_tiers, p_sq, e_sq)
    l1 = [s[0][1] for s in slots]
    l2 = [s[1][1] for s in slots]
    sim1 = bd.simulate_battle(l1, wave, p_sq, e_sq, buffs, player_tiers)
    sim2 = bd.simulate_battle(l2, wave, p_sq, e_sq, buffs, player_tiers)

    print("\n--- RECOMMENDATION OUTPUT ---")
    l1_names = [bd.resolve_unit(u, player_tiers)["short"] for u in l1]
    l2_names = [bd.resolve_unit(u, player_tiers)["short"] for u in l2]
    print(f"Lineup #1: {l1_names} ({l1}) => Loss: {sim1['loss_pct']:.1f}%")
    print(f"Lineup #2: {l2_names} ({l2}) => Loss: {sim2['loss_pct']:.1f}%")

    # 7. Testing score > 0.0 threshold for valid_slot_keys
    print("\n" + "=" * 80)
    print("7. TESTING SCORE THRESHOLD: score > 0.0 vs score > -10.0")
    print("=" * 80)
    def rec_threshold(wave, buffs, player_tiers, p_sq, e_sq, min_score=0.0):
        heuristic_slots = bd.recommend_heuristic(wave, buffs, player_tiers, p_sq, e_sq)
        slot_score_map = [{c[1]: c[0] for c in heuristic_slots[s]} for s in range(5)]

        valid_slot_keys = []
        for s in range(5):
            v_keys = [c[1] for c in heuristic_slots[s][:6] if c[0] > min_score]
            if not v_keys:
                v_keys = [heuristic_slots[s][0][1]]
            valid_slot_keys.append(v_keys)

        top1 = [heuristic_slots[s][0][1] for s in range(5)]
        top2 = [valid_slot_keys[s][min(1, len(valid_slot_keys[s]) - 1)] for s in range(5)]
        cand_lineups = [tuple(top1), tuple(top2)]

        for s in range(5):
            for v_key in valid_slot_keys[s][1:]:
                var_L = list(top1)
                var_L[s] = v_key
                cand_lineups.append(tuple(var_L))

        for u in bd.PLAYER_UNIT_KEYS:
            cohesive_L = list(top1)
            placed = 0
            for s in range(5):
                if u in valid_slot_keys[s]:
                    cohesive_L[s] = u
                    placed += 1
            if placed >= 2:
                cand_lineups.append(tuple(cohesive_L))

        unique_cands = []
        seen = set()
        for L in cand_lineups:
            if L not in seen:
                seen.add(L)
                unique_cands.append(L)

        eval_cache = {}
        def eval_lineup(L):
            t = tuple(L)
            if t in eval_cache:
                return eval_cache[t]
            sim = bd.simulate_battle(list(L), wave, p_sq, e_sq, buffs, player_tiers)
            h_avg = sum(slot_score_map[s].get(L[s], 0.0) for s in range(5)) / 5.0
            stock_pen = 5000.0 if any(slot_score_map[s].get(L[s], 0.0) < -300.0 for s in range(5)) else 0.0
            non_counter_pen = 2000.0 if any(L[s] not in valid_slot_keys[s] for s in range(5)) else 0.0
            defeat_pen = 0.0 if sim['won'] else 1000.0
            obj = stock_pen + non_counter_pen + defeat_pen + sim['loss_pct'] - (h_avg * 0.15)
            res = (obj, sim, h_avg)
            eval_cache[t] = res
            return res

        best_obj = 999999.0
        best_L = list(unique_cands[0])
        best_sim = None
        best_h_avg = 0.0
        for L in unique_cands:
            obj, sim, h_avg = eval_lineup(L)
            if obj < best_obj:
                best_obj = obj
                best_L = list(L)
                best_sim = sim
                best_h_avg = h_avg

        for s in range(5):
            cur_unit = best_L[s]
            for cand_unit in valid_slot_keys[s]:
                if cand_unit != cur_unit:
                    trial_L = list(best_L)
                    trial_L[s] = cand_unit
                    trial_obj, trial_sim, trial_h_avg = eval_lineup(trial_L)
                    if trial_obj < best_obj:
                        best_obj = trial_obj
                        best_L = trial_L
                        best_sim = trial_sim
                        best_h_avg = trial_h_avg

        final_slots = []
        for s in range(5):
            best_key = best_L[s]
            best_cand = next((c for c in heuristic_slots[s] if c[1] == best_key), heuristic_slots[s][0])

            other_valid_keys = [k for k in valid_slot_keys[s] if k != best_key]
            swap_ranked = []
            for cand_key in other_valid_keys:
                swap_L = list(best_L)
                swap_L[s] = cand_key
                swap_obj, swap_sim, swap_h = eval_lineup(swap_L)
                cand_item = next((c for c in heuristic_slots[s] if c[1] == cand_key), None)
                if cand_item:
                    swap_ranked.append((swap_obj, swap_sim['loss_pct'], swap_sim['won'], cand_item))

            swap_ranked.sort(key=lambda x: x[0])

            ranked_keys = {best_key}.union(other_valid_keys)
            remaining_cands = [c for c in heuristic_slots[s] if c[1] not in ranked_keys]

            slot_cands = [best_cand] + [item[3] for item in swap_ranked] + remaining_cands
            final_slots.append(slot_cands)

        return final_slots, best_L, best_sim

    slots_pos, l1_pos, sim_pos = rec_threshold(wave, buffs, player_tiers, p_sq, e_sq, min_score=0.0)
    l1_pos_names = [bd.resolve_unit(u, player_tiers)["short"] for u in l1_pos]
    l2_pos = [s[1][1] for s in slots_pos]
    l2_pos_names = [bd.resolve_unit(u, player_tiers)["short"] for u in l2_pos]
    sim_pos_l2 = bd.simulate_battle(l2_pos, wave, p_sq, e_sq, buffs, player_tiers)

    print(f"When min_score > 0.0 on Enc 4:")
    print(f"  Lineup #1: {l1_pos_names} ({l1_pos}) => Loss: {sim_pos['loss_pct']:.1f}%")
    print(f"  Lineup #2: {l2_pos_names} ({l2_pos}) => Loss: {sim_pos_l2['loss_pct']:.1f}%")

if __name__ == "__main__":
    main()
