#!/usr/bin/env python3
"""
Verification Script for Lineup #1 (Primary) and Lineup #2 (Backup / 1-Slot Swap)
================================================================================
Evaluates:
  1. All 40 real battles in Batte AI Data
  2. All 6 live Tournament encounters from elvenar_debug_dump_live_2026-11-07T07-51-51-232Z.json

Outputs:
  - Lineup #1: Win Rate, Avg Loss %, Counter Compliance
  - 1-Slot Swaps: Win Rate, Avg Loss %, Delta vs Lineup #1, Counter Compliance
  - Full Lineup #2: Win Rate, Avg Loss %, Delta vs Lineup #1, Counter Compliance
  - Detailed Enc 0..5 breakdown table
"""

import os
import sys
import json
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)
import benchmark_dump as bd

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

LIVE_DUMP_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "Batte AI Data", "elvenar_debug_dump_live_2026-11-07T07-51-51-232Z.json"))

def is_valid_counter(player_key, enemy_id, player_tiers=None):
    pu = bd.resolve_unit(player_key, player_tiers)
    eu = bd.resolve_unit(enemy_id, player_tiers)
    e_cls = eu["cls"]
    return (pu.get("str", {}).get(e_cls, 0) > 0 or 
            pu.get("atk", {}).get(e_cls, 0) > 0 or 
            pu.get("def", {}).get(e_cls, 0) > 0)


def verify_40_battles():
    print("=" * 100)
    print("VERIFICATION SUITE PART 1: 40 REAL BATTLES (Batte AI Data)")
    print("=" * 100)

    battles = bd.load_all_dump_battles()
    if not battles:
        print("[-] No dump battles loaded!")
        return

    city_atk = {"light_melee": .73, "light_ranged": 1.04, "mage": .90, "heavy_melee": .83, "heavy_ranged": .60}

    l1_wins, l1_losses = 0, []
    l2_wins, l2_losses = 0, []
    swap_wins, swap_losses = 0, []
    l1_comp, l2_comp, swap_comp = 0, 0, 0
    total_slots = len(battles) * 5
    total_swaps = len(battles) * 5

    for b_idx, b in enumerate(battles):
        st = b.get("state", {})
        units_order = st.get("unitsOrder", [])
        p_units = sorted([u for u in units_order if u.get("teamFlag") == 1], key=lambda u: bd.Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))
        e_units = sorted([u for u in units_order if u.get("teamFlag") == 2], key=lambda u: bd.Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))
        p_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in p_units) / 5)
        e_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in e_units) / 5)
        buffs = {"hp": p_units[0]["startHitpoints"] / p_units[0]["unitType"]["hitpoints"] - 1, "atk": city_atk}
        wave = [u["unitType"]["unitTypeId"] for u in e_units]

        slots = bd.recommend_v70(wave, buffs, None, p_sq, e_sq)
        l1 = [s[0][1] for s in slots]
        l2 = [s[1][1] for s in slots]

        sim1 = bd.simulate_battle(l1, wave, p_sq, e_sq, buffs, None)
        if sim1["won"]: l1_wins += 1
        l1_losses.append(sim1["loss_pct"])
        for s in range(5):
            if is_valid_counter(l1[s], wave[s]): l1_comp += 1

        sim2 = bd.simulate_battle(l2, wave, p_sq, e_sq, buffs, None)
        if sim2["won"]: l2_wins += 1
        l2_losses.append(sim2["loss_pct"])
        for s in range(5):
            if is_valid_counter(l2[s], wave[s]): l2_comp += 1

        for s in range(5):
            swap_L = list(l1)
            swap_L[s] = l2[s]
            sim_swap = bd.simulate_battle(swap_L, wave, p_sq, e_sq, buffs, None)
            if sim_swap["won"]: swap_wins += 1
            swap_losses.append(sim_swap["loss_pct"])
            if is_valid_counter(l2[s], wave[s]): swap_comp += 1

    l1_avg = sum(l1_losses) / len(l1_losses)
    swap_avg = sum(swap_losses) / len(swap_losses)
    l2_avg = sum(l2_losses) / len(l2_losses)

    print(f"{'Lineup Configuration':32} | {'Win Rate':16} | {'Avg Loss %':12} | {'Delta vs #1':14} | {'Counter Compliance':20}")
    print("-" * 100)
    print(f"{'Lineup #1 (Optimal Primary)':32} | {l1_wins:2d}/40 ({l1_wins/40*100:5.1f}%) | {l1_avg:9.1f}% | {'BASELINE':14} | {l1_comp:3d}/{total_slots:3d} ({l1_comp/total_slots*100:5.1f}%)")
    print(f"{'1-Slot Swaps from #2 into #1':32} | {swap_wins:3d}/200 ({swap_wins/total_swaps*100:5.1f}%) | {swap_avg:9.1f}% | {swap_avg - l1_avg:+5.1f}% pts     | {swap_comp:3d}/{total_swaps:3d} ({swap_comp/total_swaps*100:5.1f}%)")
    print(f"{'Full Lineup #2 (Backup)':32} | {l2_wins:2d}/40 ({l2_wins/40*100:5.1f}%) | {l2_avg:9.1f}% | {l2_avg - l1_avg:+5.1f}% pts     | {l2_comp:3d}/{total_slots:3d} ({l2_comp/total_slots*100:5.1f}%)")
    print("=" * 100)
    print()


def verify_6_live_tournament():
    print("=" * 100)
    print("VERIFICATION SUITE PART 2: 6 LIVE TOURNAMENT ENCOUNTERS (Enc 0..5)")
    print(f"File: {os.path.basename(LIVE_DUMP_PATH)}")
    print("=" * 100)

    if not os.path.exists(LIVE_DUMP_PATH):
        print(f"[-] Error: Live dump file not found at {LIVE_DUMP_PATH}")
        return

    with open(LIVE_DUMP_PATH, "r", encoding="utf-8") as f:
        dump = json.load(f)

    enc_vos = []
    def walk(x):
        if isinstance(x, dict):
            if x.get("__class__") == "TournamentProvinceEncountersVO":
                enc_vos.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for item in x:
                walk(item)

    for e in dump:
        data = e.get("payload") or e.get("data")
        if data:
            try:
                walk(json.loads(data) if isinstance(data, str) else data)
            except Exception:
                pass

    _, buffs, player_tiers = bd.extract_dump_data(LIVE_DUMP_PATH)
    print(f"[+] Loaded {len(enc_vos)} Tournament Province Encounters.")
    print(f"[+] Player City Buffs: HP = +{buffs['hp']*100:.1f}%, Atk: LR=+{buffs['atk']['light_ranged']*100:.0f}%, MA=+{buffs['atk']['mage']*100:.0f}%, HM=+{buffs['atk']['heavy_melee']*100:.0f}%, LM=+{buffs['atk']['light_melee']*100:.0f}%, HR=+{buffs['atk']['heavy_ranged']*100:.0f}%")
    print()

    t_l1_wins, t_l1_losses = 0, []
    t_l2_wins, t_l2_losses = 0, []
    t_swap_wins, t_swap_losses = 0, []
    t_l1_comp, t_l2_comp, t_swap_comp = 0, 0, 0

    table_rows = []

    for idx, tpe in enumerate(enc_vos):
        p_sq = tpe.get("playerSquadSize")
        wave0 = tpe["encounters"][0]["enemyWaves"][0]
        e_sq = wave0.get("squadSize")
        wave = [u["unitTypeId"] for u in wave0.get("army", [])]

        slots = bd.recommend_v70(wave, buffs, player_tiers, p_sq, e_sq)
        l1 = [s[0][1] for s in slots]
        l2 = [s[1][1] for s in slots]

        sim1 = bd.simulate_battle(l1, wave, p_sq, e_sq, buffs, player_tiers)
        if sim1["won"]: t_l1_wins += 1
        t_l1_losses.append(sim1["loss_pct"])
        for s in range(5):
            if is_valid_counter(l1[s], wave[s], player_tiers): t_l1_comp += 1

        sim2 = bd.simulate_battle(l2, wave, p_sq, e_sq, buffs, player_tiers)
        if sim2["won"]: t_l2_wins += 1
        t_l2_losses.append(sim2["loss_pct"])
        for s in range(5):
            if is_valid_counter(l2[s], wave[s], player_tiers): t_l2_comp += 1

        slot_swap_losses = []
        for s in range(5):
            swap_L = list(l1)
            swap_L[s] = l2[s]
            sim_swap = bd.simulate_battle(swap_L, wave, p_sq, e_sq, buffs, player_tiers)
            if sim_swap["won"]: t_swap_wins += 1
            t_swap_losses.append(sim_swap["loss_pct"])
            slot_swap_losses.append(sim_swap["loss_pct"])
            if is_valid_counter(l2[s], wave[s], player_tiers): t_swap_comp += 1

        e_names = "/".join(bd.resolve_unit(u, player_tiers)["short"][:4] for u in wave)
        l1_names = "/".join(bd.resolve_unit(u, player_tiers)["short"][:4] for u in l1)
        l2_names = "/".join(bd.resolve_unit(u, player_tiers)["short"][:4] for u in l2)
        swap_min = min(slot_swap_losses)
        swap_max = max(slot_swap_losses)

        table_rows.append({
            "enc": f"Enc {idx}",
            "enemy": e_names,
            "l1": f"{l1_names} ({sim1['loss_pct']:.1f}%)",
            "swap_range": f"{swap_min:.1f}% - {swap_max:.1f}%",
            "l2": f"{l2_names} ({sim2['loss_pct']:.1f}%)",
            "l1_loss": sim1["loss_pct"],
            "l2_loss": sim2["loss_pct"],
            "swaps": slot_swap_losses
        })

    t_l1_avg = sum(t_l1_losses) / len(t_l1_losses)
    t_swap_avg = sum(t_swap_losses) / len(t_swap_losses)
    t_l2_avg = sum(t_l2_losses) / len(t_l2_losses)

    print(f"{'Lineup Configuration':32} | {'Win Rate':16} | {'Avg Loss %':12} | {'Delta vs #1':14} | {'Counter Compliance':20}")
    print("-" * 100)
    print(f"{'Lineup #1 (Optimal Primary)':32} | {t_l1_wins:2d}/6  ({t_l1_wins/6*100:5.1f}%) | {t_l1_avg:9.1f}% | {'BASELINE':14} | {t_l1_comp:2d}/30 ({t_l1_comp/30*100:5.1f}%)")
    print(f"{'1-Slot Swaps from #2 into #1':32} | {t_swap_wins:2d}/30 ({t_swap_wins/30*100:5.1f}%) | {t_swap_avg:9.1f}% | {t_swap_avg - t_l1_avg:+5.1f}% pts     | {t_swap_comp:2d}/30 ({t_swap_comp/30*100:5.1f}%)")
    print(f"{'Full Lineup #2 (Backup)':32} | {t_l2_wins:2d}/6  ({t_l2_wins/6*100:5.1f}%) | {t_l2_avg:9.1f}% | {t_l2_avg - t_l1_avg:+5.1f}% pts     | {t_l2_comp:2d}/30 ({t_l2_comp/30*100:5.1f}%)")
    print("=" * 100)
    print()

    print("EXACT BREAKDOWN TABLE: LIVE TOURNAMENT ENCOUNTERS (Enc 0..5)")
    print("-" * 115)
    print(f"{'Encounter':9} | {'Enemy Lineup (S1..S5)':28} | {'Lineup #1 + Loss':28} | {'1-Slot Swap Range':19} | {'Full Lineup #2 + Loss':26}")
    print("-" * 115)
    for r in table_rows:
        print(f"{r['enc']:9} | {r['enemy']:28} | {r['l1']:28} | {r['swap_range']:19} | {r['l2']:26}")
    print("-" * 115)

    print("\nPER-SLOT SWAP LOSS DETAILS (Enc 0..5):")
    for r in table_rows:
        sw_details = " | ".join(f"S{s+1}: {loss:.1f}%" for s, loss in enumerate(r['swaps']))
        print(f"  {r['enc']}: [{sw_details}]")
    print("=" * 115)


if __name__ == "__main__":
    verify_40_battles()
    verify_6_live_tournament()
