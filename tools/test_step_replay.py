#!/usr/bin/env python3
"""
Elvenar Radar — Step-Replay Physical Combat Laws Verification (Phase P0)
========================================================================
Validates the 3 fundamental combat mechanics against 953 attacks and 178
retaliations logged in InstantBattleResultVO.state.stepHistory across all
40 standard benchmark battles.

Physical Laws Verified:
  1. Attack Modifier:
     eff_atk = (1 + atk_bonus) * (1 + attacker_atk_debuff)
     eff_def = (1 - def_bonus) * (1 - target_def_debuff)
     pred_mod = round((eff_atk * eff_def - 1) * 100)
     Target Gate: >= 99.5% match rate (Expected: 950/953 = 99.69%)

  2. Killed Units (HP Pool + topHp model):
     thp = startHitpoints if player else base_hitpoints
     pool = (amt - 1) * thp + top_hp
     rem = max(0, pool - dealt_damage)
     pred_killed = amt - ceil(rem / thp)
     Target Gate: >= 94.0% match rate within ±1 unit (Expected: 936/953 = 98.22%)

  3. Retaliation Damage (50% Counter-Attack):
     full_counter_dmg = t_cnt * baseDamage * eff_ret_mod * city_mult
     Target Gate: median ratio retaliationDamage / full_counter_dmg in [0.45, 0.52]
"""

import os
import sys
import math
import argparse
from collections import defaultdict

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

import benchmark_dump as bd  # noqa: E402
import audit_engine_fidelity as aef  # noqa: E402

DEFAULT_DUMP_FILES = [
    os.path.join(REPO_DIR, "..", "Batte AI Data", "(tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json"),
    os.path.join(REPO_DIR, "..", "Batte AI Data", "elvenar_debug_dump_live_2026-11-06T08-08-29-735Z.json"),
    os.path.join(REPO_DIR, "..", "elvenar_debug_dump_live_2026-11-05T17-50-42-275Z.json"),
    os.path.join(REPO_DIR, "..", "elvenar_debug_dump_live_2026-11-05T18-54-06-095Z.json"),
]


def load_ability_durations():
    """Builds base duration lookup table from ALL_UNITS_DB ab[] entries."""
    ab_dur = {}
    for _, udata in bd.ALL_UNITS_DB.items():
        for a in udata.get("ab", []):
            if "n" in a:
                ab_dur[a["n"].strip()] = int(a.get("d", 1))
    return ab_dur


def run_step_replay(battles, verbose=False):
    ab_dur = load_ability_durations()

    tot_attacks = 0
    mod_exact_match = 0
    mod_tol1_match = 0
    mod_mismatches = []

    killed_exact_match = 0
    killed_tol1_match = 0
    killed_mismatches = []

    tot_ret = 0
    ret_ratios = []

    for b_idx, b in enumerate(battles):
        st = b.get("state", {})
        units_order = st.get("unitsOrder", [])
        units_order_list = [u["unitId"] for u in units_order]
        units = {u["unitId"]: u for u in units_order}

        # Per-battle unit states
        debuffs = {u["unitId"]: {} for u in units_order}
        amt = {u["unitId"]: u["startAmountOfUnits"] for u in units_order}
        top_hp = {u["unitId"]: u["startHitpoints"] for u in units_order}

        prev_order_idx = -1

        for step_idx, s in enumerate(st.get("stepHistory", [])):
            uid = s.get("unitId")
            cur_order_idx = units_order_list.index(uid) if uid in units_order_list else 0

            # Round transition check: when current initiative index <= previous index
            if cur_order_idx <= prev_order_idx:
                for u_id in debuffs:
                    to_remove = []
                    for btype, binfo in debuffs[u_id].items():
                        binfo[1] -= 1
                        if binfo[1] <= 0:
                            to_remove.append(btype)
                    for btype in to_remove:
                        del debuffs[u_id][btype]
            prev_order_idx = cur_order_idx

            if "attackedUnitId" not in s:
                continue

            tot_attacks += 1
            tid = s["attackedUnitId"]
            u_att = units[uid]
            u_tgt = units[tid]
            att_type = u_att["unitType"]
            tgt_type = u_tgt["unitType"]

            # -------------------------------------------------------------
            # LAW 1: attackModifier prediction
            # -------------------------------------------------------------
            atk_b = (att_type.get("attackBonus") or {}).get(tgt_type["unitClass"], 0)
            def_b = (tgt_type.get("defenseBonus") or {}).get(att_type["unitClass"], 0)
            a_debuff = debuffs[uid].get("attack_negative", [0, 0])[0]
            d_debuff = debuffs[tid].get("defense_negative", [0, 0])[0]

            eff_atk = (1.0 + atk_b / 100.0) * (1.0 + a_debuff / 100.0)
            eff_def = (1.0 - def_b / 100.0) * (1.0 - d_debuff / 100.0)
            pred_mod = round((eff_atk * eff_def - 1.0) * 100)
            obs_mod = s.get("attackModifier", 0)

            diff_mod = abs(pred_mod - obs_mod)
            if diff_mod == 0:
                mod_exact_match += 1
            if diff_mod <= 1:
                mod_tol1_match += 1
            else:
                mod_mismatches.append((b_idx, step_idx, pred_mod, obs_mod, atk_b, def_b, a_debuff, d_debuff))

            # -------------------------------------------------------------
            # LAW 2: killedUnits prediction (HP Pool + topHp)
            # -------------------------------------------------------------
            thp = u_tgt["startHitpoints"] if u_tgt["teamFlag"] == 1 else tgt_type["hitpoints"]
            t_amt = amt[tid]
            t_top = top_hp[tid]
            dealt_damage = s.get("dealtDamage", 0)
            pool = (t_amt - 1) * thp + t_top
            rem = max(0, pool - dealt_damage)
            pred_alive = math.ceil(rem / thp) if rem > 0 else 0
            pred_killed = t_amt - pred_alive
            obs_killed = s.get("killedUnits", 0)

            diff_killed = abs(pred_killed - obs_killed)
            if diff_killed == 0:
                killed_exact_match += 1
            if diff_killed <= 1:
                killed_tol1_match += 1
            else:
                killed_mismatches.append((b_idx, step_idx, pred_killed, obs_killed, pool, dealt_damage, thp))

            # Update HP pool state for next steps
            top_hp[tid] = s.get("attackedUnitHitpoints", top_hp[tid])
            amt[tid] = s.get("attackedAmountOfUnits", amt[tid] - obs_killed)

            # Apply new debuffs onto target
            new_buffs = s.get("targetNewBuffs") or {}
            for btype, bv in new_buffs.items():
                bname = (bv.get("name") or "").strip()
                dur = ab_dur.get(bname, bv.get("duration") or 1)
                val = bv.get("value", 0)
                debuffs[tid][btype] = [val, dur]

            # -------------------------------------------------------------
            # LAW 3: retaliationDamage (50% counterattack after taking hits)
            # -------------------------------------------------------------
            ret_dmg = s.get("retaliationDamage", -1)
            if ret_dmg > 0:
                tot_ret += 1
                t_cnt = amt[tid]  # Remaining squad count after taking damage
                ret_atk_b = (tgt_type.get("attackBonus") or {}).get(att_type["unitClass"], 0)
                ret_def_b = (att_type.get("defenseBonus") or {}).get(tgt_type["unitClass"], 0)
                ret_a_deb = debuffs[tid].get("attack_negative", [0, 0])[0]
                ret_d_deb = debuffs[uid].get("defense_negative", [0, 0])[0]

                eff_ret_mod = (1.0 + ret_atk_b / 100.0) * (1.0 + ret_a_deb / 100.0) * (1.0 - ret_def_b / 100.0) * (1.0 - ret_d_deb / 100.0)
                city_mult = 1.0 + aef.CITY_ATK.get(tgt_type["unitClass"], 0.0) if u_tgt["teamFlag"] == 1 else 1.0

                full_counter_dmg = t_cnt * tgt_type["baseDamage"] * eff_ret_mod * city_mult
                if full_counter_dmg > 0:
                    ret_ratios.append(ret_dmg / full_counter_dmg)

    return {
        "tot_attacks": tot_attacks,
        "mod_exact_match": mod_exact_match,
        "mod_tol1_match": mod_tol1_match,
        "mod_mismatches": mod_mismatches,
        "killed_exact_match": killed_exact_match,
        "killed_tol1_match": killed_tol1_match,
        "killed_mismatches": killed_mismatches,
        "tot_ret": tot_ret,
        "ret_ratios": ret_ratios,
    }


def main():
    parser = argparse.ArgumentParser(description="Elvenar Radar — Step-Replay Physical Laws Verification")
    parser.add_argument("files", nargs="*", help="Paths to dump JSON files (defaults to standard 4 dump files)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print mismatch details")
    args = parser.parse_args()

    files = args.files or [f for f in DEFAULT_DUMP_FILES if os.path.exists(f)]
    if not files:
        print("[-] No dump files found.")
        sys.exit(1)

    print("=" * 85)
    print("ELVENAR RADAR — STEP-REPLAY COMBAT LAWS VERIFICATION")
    print("=" * 85)
    print(f"[+] Loaded Dump Files ({len(files)}):")
    for f in files:
        print(f"    - {os.path.basename(f)}")

    battles = aef.load_battles(files)
    print(f"[+] Total Battles Ingested: {len(battles)}")

    res = run_step_replay(battles, verbose=args.verbose)
    N_atk = res["tot_attacks"]
    N_ret = res["tot_ret"]

    print("\n" + "=" * 85)
    print("1. LAW 1: ATTACK MODIFIER (eff_atk * eff_def - 1) & DEBUFF ENGINE")
    print("=" * 85)
    mod_tol1_pct = res["mod_tol1_match"] / N_atk * 100.0 if N_atk > 0 else 0.0
    mod_exact_pct = res["mod_exact_match"] / N_atk * 100.0 if N_atk > 0 else 0.0
    print(f"   Total Attacks Evaluated : {N_atk}")
    print(f"   Exact Match (diff == 0) : {res['mod_exact_match']}/{N_atk} ({mod_exact_pct:.2f}%)")
    print(f"   Tolerance ±1 Match      : {res['mod_tol1_match']}/{N_atk} ({mod_tol1_pct:.2f}%)")
    print(f"   Expected Benchmark      : 950/953 (99.69%)")
    if res["mod_mismatches"] and args.verbose:
        print("\n   [!] Mismatches (first 5):")
        for m in res["mod_mismatches"][:5]:
            print(f"       Battle {m[0]} Step {m[1]}: pred={m[2]} obs={m[3]} (atk_b={m[4]} def_b={m[5]} a_deb={m[6]} d_deb={m[7]})")

    print("\n" + "=" * 85)
    print("2. LAW 2: KILLED UNITS (HP POOL + topHp MODEL)")
    print("=" * 85)
    k_tol1_pct = res["killed_tol1_match"] / N_atk * 100.0 if N_atk > 0 else 0.0
    k_exact_pct = res["killed_exact_match"] / N_atk * 100.0 if N_atk > 0 else 0.0
    print(f"   Total Attacks Evaluated : {N_atk}")
    print(f"   Exact Match (diff == 0) : {res['killed_exact_match']}/{N_atk} ({k_exact_pct:.2f}%)")
    print(f"   Tolerance ±1 Match      : {res['killed_tol1_match']}/{N_atk} ({k_tol1_pct:.2f}%)")
    print(f"   Acceptance Threshold    : >= 94.00%")

    print("\n" + "=" * 85)
    print("3. LAW 3: RETALIATION DAMAGE (50% COUNTER-ATTACK)")
    print("=" * 85)
    ratios = sorted(res["ret_ratios"])
    nr = len(ratios)
    p25 = ratios[int(nr * 0.25)] if nr > 0 else 0.0
    p50 = ratios[int(nr * 0.50)] if nr > 0 else 0.0
    p75 = ratios[int(nr * 0.75)] if nr > 0 else 0.0
    print(f"   Total Retaliation Events: {N_ret}")
    print(f"   Ratio (retaliationDamage / full_counter_dmg):")
    print(f"     - p25 (25th percentile): {p25:.3f}")
    print(f"     - p50 (Median)         : {p50:.3f}   [Expected: ~0.47 - 0.50]")
    print(f"     - p75 (75th percentile): {p75:.3f}")

    # Acceptance gate checks
    gate1 = mod_tol1_pct >= 99.5
    gate2 = k_tol1_pct >= 94.0
    gate3 = 0.45 <= p50 <= 0.52

    print("\n" + "=" * 85)
    print("ACCEPTANCE GATE EVALUATION (PHASE P0)")
    print("=" * 85)
    print(f"   [Gate 1] Attack Modifier (>= 99.50%): {'PASS' if gate1 else 'FAIL'} ({mod_tol1_pct:.2f}%)")
    print(f"   [Gate 2] Killed Units ±1 (>= 94.00%): {'PASS' if gate2 else 'FAIL'} ({k_tol1_pct:.2f}%)")
    print(f"   [Gate 3] Retaliation Median in [0.45, 0.52]: {'PASS' if gate3 else 'FAIL'} ({p50:.3f})")

    if gate1 and gate2 and gate3:
        print("\n>>> ALL PHASE P0 ACCEPTANCE GATES PASSED! <<<")
        sys.exit(0)
    else:
        print("\n>>> ONE OR MORE ACCEPTANCE GATES FAILED! <<<")
        sys.exit(1)


if __name__ == "__main__":
    main()
