import sys
sys.path.append(r'D:\ElvenarAuto\elvenar-dashboard\tools')
import benchmark_dump as bd

wave = ['mob_hblr_3', 'mob_hblm_3', 'mob_tglr_3', 'mob_tglr_3', 'mob_hblm_3']
player_lineup = ['tg_hr', 'tg_hr', 'tg_hr', 'tg_hr', 'eb_hr']
buffs = {'hp': 0.775, 'atk': {'light_melee': .73, 'light_ranged': 0.89, 'mage': .90, 'heavy_melee': .83, 'heavy_ranged': .60}}
p_sq = 24000
e_sq = 48572
player_tiers = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 2, 2]

p_units = []
for s in range(5):
    u = bd.resolve_unit(player_lineup[s], player_tiers)
    u_cnt = int(p_sq / u['wt'])
    hp_per_u = u['hp'] * (1.0 + buffs['hp'])
    dmg_per_u = u['dmg'] * (1.0 + buffs['atk'].get(u['cls'], 0.0))
    p_units.append({
        'id': f'P_{s+1}', 'team': 1, 'slot': s, 'u': u, 'cls': u['cls'],
        'count': u_cnt, 'start_count': u_cnt, 'hp_per_unit': hp_per_u, 'dmg_per_unit': dmg_per_u,
        'hp_pool': u_cnt * hp_per_u, 'x': 0, 'y': bd.SLOT_Y[s],
        'mv': u['mv'], 'rng': u['rng'], 'init': u['init'], 'wt': u['wt'],
        'ret_left': u.get('ret', 1), 'ret_max': u.get('ret', 1),
        'atk_debuff': {'val': 0.0, 'dur': 0}, 'def_debuff': {'val': 0.0, 'dur': 0}
    })

e_units = []
for s in range(5):
    u = bd.resolve_unit(wave[s], player_tiers)
    u_cnt = int(e_sq / u['wt'])
    hp_per_u = u['hp']
    dmg_per_u = u['dmg']
    e_units.append({
        'id': f'E_{s+1}', 'team': 2, 'slot': s, 'u': u, 'cls': u['cls'],
        'count': u_cnt, 'start_count': u_cnt, 'hp_per_unit': hp_per_u, 'dmg_per_unit': dmg_per_u,
        'hp_pool': u_cnt * hp_per_u, 'x': 7, 'y': bd.SLOT_Y[s],
        'mv': u['mv'], 'rng': u['rng'], 'init': u['init'], 'wt': u['wt'],
        'ret_left': u.get('ret', 1), 'ret_max': u.get('ret', 1),
        'atk_debuff': {'val': 0.0, 'dur': 0}, 'def_debuff': {'val': 0.0, 'dur': 0}
    })

def calc_eff_mult(attacker, target):
    atk_b = (attacker["u"].get("atk", {}).get(target["cls"], 0)) / 100.0
    def_b = (target["u"].get("def", {}).get(attacker["cls"], 0)) / 100.0
    a_deb = attacker["atk_debuff"]["val"] / 100.0
    d_deb = target["def_debuff"]["val"] / 100.0
    return (1.0 + atk_b) * (1.0 + a_deb) * (1.0 - def_b) * (1.0 - d_deb)

DMG_EXPECTED_MULT = 1.07
print("=== BATTLE 1 STEP-BY-STEP SIMULATION LOG ===")
for r in range(1, 4):
    print(f"\n--- ROUND {r} ---")
    all_units = [u for u in p_units + e_units if u["count"] > 0]
    all_units.sort(key=lambda u: (u["init"], 1 if u["team"] == 1 else 0, u["slot"]), reverse=True)
    for attacker in all_units:
        if attacker["count"] <= 0: continue
        targets = [u for u in (e_units if attacker["team"] == 1 else p_units) if u["count"] > 0]
        if not targets: break
        
        start = (attacker["x"], attacker["y"])
        blocked = {(u["x"], u["y"]) for u in p_units + e_units if u["count"] > 0 and u["id"] != attacker["id"]}
        reach_cells = bd.bfs_reachable(start, attacker["mv"], blocked)
        
        cand_targets = []
        for tgt in targets:
            tpos = (tgt["x"], tgt["y"])
            valid_cells = [c for c in reach_cells if bd.hex_dist(c, tpos) <= attacker["rng"]]
            if valid_cells:
                min_steps = min(reach_cells[c] for c in valid_cells)
                if attacker["rng"] > 1:
                    home_sign = 1 if attacker["team"] == 1 else -1
                    best_c = min(valid_cells, key=lambda c: (-bd.hex_dist(c, tpos), home_sign * c[0], reach_cells[c]))
                else:
                    best_c = min(valid_cells, key=lambda c: (reach_cells[c], abs(c[1] - start[1])))
                cand_targets.append((tgt, best_c, min_steps))
        
        if not cand_targets:
            # Advance
            if attacker["rng"] == 1 and reach_cells:
                # move towards closest target
                closest_t = min(targets, key=lambda t: bd.hex_dist(start, (t["x"], t["y"])))
                tpos = (closest_t["x"], closest_t["y"])
                best_c = min(reach_cells.keys(), key=lambda c: (bd.hex_dist(c, tpos), reach_cells[c]))
                attacker["x"], attacker["y"] = best_c
                print(f"  {attacker['id']} ({attacker['u']['name']}) ADVANCED from {start} to {best_c} towards {closest_t['id']}")
            continue
            
        cand_evals = []
        for tgt, best_c, min_steps in cand_targets:
            em = calc_eff_mult(attacker, tgt)
            edmg = attacker["count"] * attacker["dmg_per_unit"] * em * DMG_EXPECTED_MULT
            kr = min(1.0, edmg / max(1.0, tgt["hp_pool"]))
            d_now = bd.hex_dist(start, (tgt["x"], tgt["y"]))
            fb = 0.0
            if attacker["team"] == 2:
                bhp = (tgt["hp_per_unit"] / (1.0 + buffs["hp"])) / tgt["wt"]
                if bhp < 120:
                    fb = (120.0 - bhp) * 0.8
            score = ((em - 1.0) * 180.0) + (kr * 80.0) - (min_steps * 12.0) - (d_now * 6.0) + fb
            cand_evals.append((score, tgt, best_c, em, kr, d_now, min_steps, fb))
            
        cand_evals.sort(key=lambda x: x[0], reverse=True)
        best_score, best_t, best_pos, em, kr, d_now, min_steps, fb = cand_evals[0]
        attacker["x"], attacker["y"] = best_pos
        eff_mult = calc_eff_mult(attacker, best_t)
        dealt_dmg = attacker["count"] * attacker["dmg_per_unit"] * eff_mult * DMG_EXPECTED_MULT
        old_count = best_t["count"]
        best_t["hp_pool"] = max(0.0, best_t["hp_pool"] - dealt_dmg)
        best_t["count"] = int(best_t["hp_pool"] / best_t["hp_per_unit"]) if best_t["hp_pool"] > 0 else 0
        loss = old_count - best_t["count"]
        print(f"  {attacker['id']} ({attacker['u']['name']}) at {start}->{best_pos} ATTACKED {best_t['id']} ({best_t['u']['name']})! Score={best_score:.1f} (em={em:.2f}, kr={kr:.2f}, d_now={d_now}, min_steps={min_steps}, fb={fb:.1f}) -> killed {loss} units (now {best_t['count']}/{best_t['start_count']})")
        if len(cand_evals) > 1:
            print(f"    Other cands: {[(c[1]['id'], round(c[0], 1), 'em='+str(round(c[3], 2)), 'd='+str(c[5])) for c in cand_evals[1:]]}")
