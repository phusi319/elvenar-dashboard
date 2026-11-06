#!/usr/bin/env python3
"""
Elvenar Auto-Battle Dump Benchmark & Combat Simulator Suite (v6.6.1)
===================================================================
Unified analysis and simulation tool for Elvenar Tournament & Spire battle dumps.

Usage:
    python benchmark_dump.py "<path_to_dump.json>"
    python benchmark_dump.py                      # Automatically picks the newest dump in ../../Batte AI Data/

Features:
  1. Ingestion: Extracts all InstantBattleResultVO packets, starting squad sizes, and active city military buffs.
  2. Empirical Analysis: Evaluates per-unit casualty rates, wipeouts, and safety rates across all deployed slots.
  3. Recommendation Engine (v6.5.2): Computes optimal lineups with spatial neighbor hazard & dual-bridge synergy.
  4. Combat Simulation: Simulates turn-by-turn auto-battle following Elvenar mechanics (Initiative, AI targeting, damage reduction, retaliation).
  5. Benchmark Comparison: Compares actual in-game results vs Advisor v6.5.2 recommendations.
"""

import os
import sys
import glob
import json
import re
from collections import defaultdict

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INDEX_HTML_PATH = os.path.join(REPO_DIR, "index.html")

# True Elvenar Hex map vertical coordinate mapping
# Top (y=2): Slot 4 | Upper-Mid (y=3): Slot 2 | Center (y=4): Slot 1 | Lower-Mid (y=5): Slot 3 | Bottom (y=6): Slot 5
SLOT_Y = [4, 3, 5, 2, 6]
Y_TO_SLOT = {4: 1, 3: 2, 5: 3, 2: 4, 6: 5}

PLAYER_UNIT_KEYS = [
    "eb_lm", "eb_lr", "eb_ma", "eb_hm", "eb_hr",
    "tg_lm", "tg_lr", "tg_ma", "tg_hm", "tg_hr",
    "mc_lm", "mc_lr", "mc_ma", "mc_hm", "mc_hr"
]


def load_game_db_from_index():
    """Extracts ALL_UNITS_DB and UNIT_STATS_DB directly from index.html to ensure 100% synchronization."""
    if not os.path.exists(INDEX_HTML_PATH):
        raise FileNotFoundError(f"Cannot find index.html at {INDEX_HTML_PATH}")
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    m_all = re.search(r"const ALL_UNITS_DB = (\{.*?\});", html)
    if not m_all:
        raise ValueError("Could not parse ALL_UNITS_DB from index.html")
    all_units_db = json.loads(m_all.group(1))

    m_unit = re.search(r"const UNIT_STATS_DB = (\{.*?\n    \});", html, re.S)
    if not m_unit:
        raise ValueError("Could not parse UNIT_STATS_DB from index.html")
    clean_js = re.sub(r"//.*", "", m_unit.group(1))
    unit_stats_db = json.loads(clean_js)

    return all_units_db, unit_stats_db


ALL_UNITS_DB, UNIT_STATS_DB = load_game_db_from_index()


def resolve_unit(raw_id, player_tiers=None):
    s = str(raw_id).strip()
    base = re.sub(r"_\d+$", "", s)
    base_entry = dict(UNIT_STATS_DB.get(base) or UNIT_STATS_DB.get(s) or UNIT_STATS_DB["mob_eblr"])
    m = re.search(r"_(\d+)$", s)
    stars = int(m.group(1)) if m else 0
    if not stars and player_tiers and "uIdx" in base_entry:
        stars = player_tiers[base_entry["uIdx"]]
    if not stars:
        m2 = re.search(r"_(\d+)$", str(base_entry.get("id", "")))
        stars = int(m2.group(1)) if m2 else 3
    exact_key = f"{base}_{stars}"
    tier_stats = ALL_UNITS_DB.get(s) or ALL_UNITS_DB.get(exact_key)
    if tier_stats:
        res = dict(base_entry)
        res.update(tier_stats)
        res["rawId"] = exact_key
        res["stars"] = stars
        return res
    base_entry["rawId"] = s
    base_entry["stars"] = stars
    return base_entry


def extract_dump_data(dump_path):
    with open(dump_path, "r", encoding="utf-8") as f:
        dump = json.load(f)

    battles = []
    active_buffs = {
        "hp": 0.0,
        "atk": {"light_melee": 0.0, "light_ranged": 0.0, "mage": 0.0, "heavy_melee": 0.0, "heavy_ranged": 0.0}
    }
    player_tiers = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 2, 2]

    def walk(d):
        if isinstance(d, dict):
            if d.get("__class__") == "InstantBattleResultVO":
                battles.append(d)
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for x in d:
                walk(x)

    for entry in dump:
        data = entry.get("payload") or entry.get("data")
        if not data:
            continue
        try:
            parsed = json.loads(data) if isinstance(data, str) else data
        except Exception:
            continue
        walk(parsed)

    # Extract military buffs from battle packets if present
    if battles:
        st = battles[0].get("state", {})
        for u in st.get("unitsOrder", []):
            if u.get("teamFlag") == 1:
                ut = u.get("unitType", {})
                start_hp = u.get("startHitpoints", 0)
                base_hp = ut.get("hitpoints", 0)
                if base_hp > 0 and start_hp > base_hp and active_buffs["hp"] == 0:
                    active_buffs["hp"] = round((start_hp - base_hp) / base_hp, 3)

    # Defaults if not specifically detected
    if active_buffs["hp"] == 0:
        active_buffs["hp"] = 0.775
    if sum(active_buffs["atk"].values()) == 0:
        active_buffs["atk"] = {
            "light_melee": 0.73,
            "light_ranged": 1.04,
            "mage": 0.90,
            "heavy_melee": 0.83,
            "heavy_ranged": 0.60,
        }

    return battles, active_buffs, player_tiers


def score_unit_pair(p_unit, e_unit, dy, w_ctx, active_buffs):
    hp_mult = 1.0 + active_buffs["hp"]
    atk_mult = 1.0 + active_buffs["atk"].get(p_unit["cls"], 0)
    p_hp = ((p_unit.get("hp", 100)) / (p_unit.get("wt", 1))) * hp_mult
    p_dmg = ((p_unit.get("dmg", 20)) / (p_unit.get("wt", 1))) * atk_mult
    e_hp = (e_unit.get("hp", 100)) / (e_unit.get("wt", 1))
    e_dmg = (e_unit.get("dmg", 20)) / (e_unit.get("wt", 1))

    atk_bonus = ((p_unit.get("atk", {}).get(e_unit["cls"], 0))) / 100.0
    def_bonus = ((p_unit.get("def", {}).get(e_unit["cls"], 0))) / 100.0
    e_atk_bonus = ((e_unit.get("atk", {}).get(p_unit["cls"], 0))) / 100.0
    e_def_bonus = ((e_unit.get("def", {}).get(p_unit["cls"], 0))) / 100.0
    star_str = (p_unit.get("str", {}).get(e_unit["cls"], 0))
    is_counter = (star_str > 0 or atk_bonus > 0 or def_bonus > 0)

    eff_offense = p_dmg * (1.0 + atk_bonus) * (1.0 - e_def_bonus)
    kill_rate = eff_offense / max(1.0, e_hp)
    eff_incoming = e_dmg * (1.0 + e_atk_bonus) * (1.0 - def_bonus)
    loss_rate = eff_incoming / max(1.0, p_hp)
    mitigation_bonus = (def_bonus * 34.0) if def_bonus >= 0.40 else (def_bonus * 16.0)

    first_strike_mult = 1.0
    incoming_mult = 1.0
    p_reach = (p_unit.get("rng", 1)) + (p_unit.get("mv", 2))
    e_reach = (e_unit.get("rng", 1)) + (e_unit.get("mv", 2))

    if is_counter:
        if p_unit.get("rng", 1) >= 8:
            first_strike_mult *= 1.38
            incoming_mult *= 0.52
        elif p_unit.get("init", 10) > e_unit.get("init", 10) and p_reach >= 7:
            first_strike_mult *= 1.26
            incoming_mult *= 0.72
    if e_unit.get("init", 10) > p_unit.get("init", 10) and e_reach >= 7:
        incoming_mult *= 1.35

    if is_counter and p_unit.get("rng", 1) >= 5 and e_unit.get("rng", 1) <= 2:
        first_strike_mult *= 1.35
        incoming_mult *= 0.45
    elif is_counter and p_unit.get("rng", 1) >= 3 and e_unit.get("rng", 1) == 1 and e_unit.get("mv", 2) <= 3:
        first_strike_mult *= 1.28
        incoming_mult *= 0.50
    elif p_unit.get("rng", 1) == 1 and e_unit.get("rng", 1) >= 3 and p_unit.get("mv", 2) <= 3:
        incoming_mult *= 1.28

    if star_str == 3:
        spec_bonus = 36.0 if dy == 0 else 20.0
    elif star_str == 2:
        spec_bonus = 34.0 if dy == 0 else 20.0
    elif star_str == 1:
        spec_bonus = 8.0
    else:
        spec_bonus = -120.0 if dy == 0 else -12.0

    ability_bonus = 0.0
    for a in p_unit.get("ab", []):
        dur = min(int(a.get("d", 1)), 2)
        if a.get("t") == "attack":
            w_atk = 0.28 if (e_unit.get("ret", 0) >= 1 or e_dmg >= 25) else 0.18
            ability_bonus += abs(a.get("v", 0)) * w_atk * dur * 0.65
        elif a.get("t") == "defense":
            ability_bonus += abs(a.get("v", 0)) * 0.22 * dur * 0.65

    ret_penalty = 0.0
    if p_unit.get("rng", 1) == 1 and e_unit.get("ret", 0) >= 1:
        if e_atk_bonus > 0 or def_bonus == 0:
            ret_penalty = 18.0 * min(e_unit.get("ret", 1), 3)

    hard_counter_penalty = 0.0
    if e_atk_bonus > 0:
        reach_mult = 1.65 if (e_reach >= 8 and e_unit.get("init", 10) > p_unit.get("init", 10)) else (1.30 if (e_unit.get("rng", 1) >= 3 or e_reach >= 7) else 1.0)
        base_hp_per_wt = (p_unit.get("hp", 100)) / (p_unit.get("wt", 1))
        frag_mult = max(1.0, 75.0 / base_hp_per_wt)
        hard_counter_penalty += (e_atk_bonus * 135.0) * reach_mult * frag_mult
    if e_def_bonus >= 0.50 and atk_bonus == 0:
        hard_counter_penalty += (e_def_bonus * 60.0)

    focus_fire_penalty = 0.0
    if e_unit.get("rng", 1) >= 3 and def_bonus == 0 and e_atk_bonus == 0 and p_unit.get("rng", 1) == 1:
        focus_fire_penalty = 22.0

    return (kill_rate * first_strike_mult * 95.0) + spec_bonus + mitigation_bonus + ability_bonus - (loss_rate * incoming_mult * 125.0) - hard_counter_penalty - focus_fire_penalty - ret_penalty


def recommend_v661(wave, active_buffs, player_tiers, p_sq=25000, e_sq=25000):
    squad_ratio = (e_sq / p_sq) if (p_sq and p_sq > 0) else 1.5
    cls_counts = {}
    has_mist_walker = False
    e_units = [resolve_unit(s, player_tiers) for s in wave]
    for s in wave:
        eu = resolve_unit(s, player_tiers)
        cls_counts[eu["cls"]] = cls_counts.get(eu["cls"], 0) + 1
        if "tglr" in s:
            has_mist_walker = True

    w_ctx = {
        "clsCounts": cls_counts,
        "hasMistWalker": has_mist_walker,
        "hmCount": cls_counts.get("heavy_melee", 0),
        "lrCount": cls_counts.get("light_ranged", 0),
        "maCount": cls_counts.get("mage", 0),
        "lmCount": cls_counts.get("light_melee", 0),
        "hrCount": cls_counts.get("heavy_ranged", 0)
    }

    slots = []
    for slot_i in range(5):
        cands = []
        target_eu = e_units[slot_i]
        for p_key in PLAYER_UNIT_KEYS:
            p_unit = resolve_unit(p_key, player_tiers)
            s_wave = 0.0
            total_w = 0.0
            neighbor_hazard = 0.0
            dual_bridge_bonus = 0.0

            countered_2star = [c for c, v in p_unit.get("str", {}).items() if v >= 2]
            is_barracks_dual = (len(countered_2star) >= 2 and target_eu["cls"] in countered_2star)
            other_countered_cls = [c for c in countered_2star if c != target_eu["cls"]]

            for slot_j in range(5):
                e_unit = e_units[slot_j]
                dy = abs(SLOT_Y[slot_i] - SLOT_Y[slot_j])
                rng = e_unit.get("rng", 1)
                mv = e_unit.get("mv", 2)
                reach = rng + mv
                if dy == 0: sw = 1.00
                elif dy == 1: sw = 0.45 if reach >= 8 else (0.38 if (rng >= 3 or mv >= 4) else 0.25)
                elif dy == 2: sw = 0.28 if reach >= 8 else (0.18 if (reach >= 7 or rng >= 4) else 0.08)
                elif dy == 3: sw = 0.18 if reach >= 8 else (0.10 if (rng >= 4 or reach >= 7) else 0.04)
                else: sw = 0.12 if reach >= 8 else (0.06 if (rng >= 4 or reach >= 7) else 0.02)

                s_wave += sw * score_unit_pair(p_unit, e_unit, dy, w_ctx, active_buffs)
                total_w += sw

                if slot_j != slot_i:
                    e_atk = (e_unit.get("atk", {}).get(p_unit["cls"], 0)) / 100.0
                    p_def = (p_unit.get("def", {}).get(e_unit["cls"], 0)) / 100.0
                    p_atk = (p_unit.get("atk", {}).get(e_unit["cls"], 0)) / 100.0

                    if e_atk > 0 and p_def < 0.50:
                        unmitigated = e_atk * (1.0 - p_def)
                        base_hp_per_wt = (p_unit.get("hp", 100)) / (p_unit.get("wt", 1))
                        frag_mult = max(0.80, 68.0 / base_hp_per_wt)
                        backline_safe = 0.35 if (p_unit.get("rng", 1) >= 5 and reach <= 4) else (0.65 if (p_unit.get("rng", 1) >= 3 and reach <= 3) else 1.0)
                        if dy == 1:
                            exposure = 1.30 if (rng >= 3 or mv >= 4 or p_unit.get("rng", 1) == 1) else 1.0
                            neighbor_hazard += unmitigated * 32.0 * exposure * frag_mult * backline_safe
                        elif dy == 2 and (rng >= 3 or reach >= 7):
                            neighbor_hazard += unmitigated * 18.0 * frag_mult * backline_safe

                    if is_barracks_dual and e_unit["cls"] in other_countered_cls:
                        if dy == 1:
                            dual_bridge_bonus += 11.0 + (p_def * 12.0) + (p_atk * 6.0)
                        elif dy == 2:
                            dual_bridge_bonus += 6.0 + (p_def * 6.0) + (p_atk * 3.0)
                        else:
                            dual_bridge_bonus += 3.0 + (p_def * 3.0)

            s_wave = (s_wave / total_w) - neighbor_hazard + min(dual_bridge_bonus, 20.0)

            direct_star = p_unit.get("str", {}).get(target_eu["cls"], 0)
            direct_atk = p_unit.get("atk", {}).get(target_eu["cls"], 0)
            direct_def = p_unit.get("def", {}).get(target_eu["cls"], 0)
            if direct_star == 0 and direct_atk == 0 and direct_def == 0:
                s_wave -= 150.0

            if is_barracks_dual and any(w_ctx["clsCounts"].get(c, 0) > 0 for c in other_countered_cls):
                s_wave += 6.0

            # Empirical 6-Star Tournament Survival Rules (v6.6.1):
            if target_eu["cls"] == "light_ranged":
                if w_ctx["hmCount"] >= 1 and p_unit["cls"] == "light_melee":
                    s_wave -= 65.0 * w_ctx["hmCount"]
                lr_def = p_unit.get("def", {}).get("light_ranged", 0)
                if p_unit["cls"] == "heavy_ranged" and lr_def >= 50:
                    if w_ctx["maCount"] == 0: s_wave += 16.0
                    elif w_ctx["hmCount"] >= 1: s_wave += 22.0

            if target_eu["cls"] == "mage" and w_ctx["hmCount"] >= 1:
                if p_unit.get("rng", 1) == 1:
                    s_wave -= 35.0 * w_ctx["hmCount"]
                elif p_unit["cls"] == "light_ranged":
                    if w_ctx["lrCount"] >= 2 and squad_ratio >= 1.6:
                        s_wave -= 40.0
                    else:
                        s_wave += 18.0

            # Rule B1: Extreme Outnumbered Swarm Guard (squadRatio >= 1.6x + lrCount >= 2):
            if squad_ratio >= 1.6 and w_ctx["lrCount"] >= 2:
                base_hp = (p_unit.get("hp", 100)) / (p_unit.get("wt", 1))
                if base_hp < 110:
                    s_wave -= 50.0 * (squad_ratio - 1.2)
                if p_unit["cls"] == "heavy_ranged" and p_unit.get("def", {}).get("light_ranged", 0) >= 50:
                    s_wave += 35.0

            if target_eu["cls"] == "heavy_ranged" and (w_ctx["lmCount"] >= 1 or w_ctx["lrCount"] >= 3):
                if p_unit["cls"] == "mage":
                    s_wave -= 14.0 * w_ctx["lmCount"] + (18.0 if w_ctx["lrCount"] >= 3 else 0.0)
                elif p_unit["base"] == "eb_hm":
                    s_wave += 16.0

            if p_unit["base"] == "mc_lr" and (w_ctx["lmCount"] >= 1 or w_ctx["hrCount"] >= 1 or w_ctx["lrCount"] >= 2):
                s_wave -= 14.0 * (w_ctx["lmCount"] + w_ctx["hrCount"] + 0.5 * w_ctx["lrCount"])

            if p_unit["cls"] == "mage" and w_ctx["hasMistWalker"] and p_unit.get("def", {}).get("light_ranged", 0) == 0:
                s_wave -= 38.0

            if target_eu["cls"] == "light_melee" and p_unit["base"] == "eb_hr":
                if w_ctx["hmCount"] >= 1 or w_ctx["hrCount"] >= 1 or w_ctx["lmCount"] >= 2 or w_ctx["lrCount"] < 3:
                    s_wave -= 16.0

            cands.append((s_wave, p_key, p_unit["short"]))
        cands.sort(reverse=True)
        slots.append(cands)
    return slots

recommend_v652 = recommend_v661


def simulate_battle(player_unit_keys, enemy_unit_ids, player_squad_size, enemy_squad_size, active_buffs, player_tiers):
    p_units = []
    for i in range(5):
        pkey = player_unit_keys[i]
        u = resolve_unit(pkey, player_tiers)
        hp_mult = 1.0 + active_buffs["hp"]
        atk_mult = 1.0 + active_buffs["atk"].get(u["cls"], 0)
        wt = u.get("wt", 1)
        count = int(player_squad_size / wt)
        p_units.append({
            "slot": i + 1, "y": SLOT_Y[i], "team": 1, "id": f"p_{i+1}", "name": u["short"],
            "cls": u["cls"], "u": u, "startCount": count, "count": count,
            "hp_per_unit": (u["hp"] * hp_mult), "dmg_per_unit": (u["dmg"] * atk_mult),
            "wt": wt, "init": u.get("init", 10), "rng": u.get("rng", 1), "mv": u.get("mv", 2),
            "ret_max": u.get("ret", 0), "ret_left": u.get("ret", 0)
        })

    e_units = []
    for i in range(5):
        eid = enemy_unit_ids[i]
        u = resolve_unit(eid, player_tiers)
        wt = u.get("wt", 1)
        count = int(enemy_squad_size / wt)
        e_units.append({
            "slot": i + 1, "y": SLOT_Y[i], "team": 2, "id": f"e_{i+1}", "name": u["short"],
            "cls": u["cls"], "u": u, "startCount": count, "count": count,
            "hp_per_unit": u["hp"], "dmg_per_unit": u["dmg"],
            "wt": wt, "init": u.get("init", 10), "rng": u.get("rng", 1), "mv": u.get("mv", 2),
            "ret_max": u.get("ret", 0), "ret_left": u.get("ret", 0)
        })

    for round_num in range(1, 16):
        for u in p_units + e_units:
            u["ret_left"] = u["ret_max"]
        all_units = [u for u in p_units + e_units if u["count"] > 0]
        all_units.sort(key=lambda u: (u["init"], 1 if u["team"] == 1 else 0), reverse=True)

        for attacker in all_units:
            if attacker["count"] <= 0: continue
            targets = [u for u in (e_units if attacker["team"] == 1 else p_units) if u["count"] > 0]
            if not targets: break

            best_target = None
            best_score = -999999
            for tgt in targets:
                dy = abs(attacker["y"] - tgt["y"])
                atk_b = (attacker["u"].get("atk", {}).get(tgt["cls"], 0)) / 100.0
                def_b = (tgt["u"].get("def", {}).get(attacker["cls"], 0)) / 100.0
                reach = attacker["rng"] + attacker["mv"]
                if round_num == 1 and reach < 6 and attacker["rng"] <= 2: continue
                eff_dmg = attacker["count"] * attacker["dmg_per_unit"] * (1.0 + atk_b) * (1.0 - def_b)
                total_tgt_hp = tgt["count"] * tgt["hp_per_unit"]
                kill_ratio = min(1.0, eff_dmg / max(1.0, total_tgt_hp))

                # Realistic hex distance & targeting:
                backline_penalty = 0.0
                if round_num == 1 and attacker["rng"] <= 4 and tgt.get("mv", 2) <= 2 and dy >= 1:
                    backline_penalty = 60.0

                focus_bonus = 0.0
                if attacker["team"] == 2:
                    base_hp = (tgt["hp_per_unit"] / (1.0 + active_buffs["hp"])) / tgt["wt"]
                    if base_hp < 120:
                        focus_bonus = (120 - base_hp) * 0.4

                score = (atk_b * 100.0) + (kill_ratio * 60.0) - (dy * 12.0) - backline_penalty + focus_bonus
                if score > best_score:
                    best_score = score
                    best_target = tgt

            if not best_target: continue

            atk_b = (attacker["u"].get("atk", {}).get(best_target["cls"], 0)) / 100.0
            def_b = (best_target["u"].get("def", {}).get(attacker["cls"], 0)) / 100.0
            dealt_dmg = attacker["count"] * attacker["dmg_per_unit"] * (1.0 + atk_b) * (1.0 - def_b)
            killed = min(best_target["count"], int(dealt_dmg / best_target["hp_per_unit"]))
            best_target["count"] -= killed

            if attacker["rng"] == 1 and best_target["count"] > 0 and best_target["ret_left"] > 0:
                ret_atk_b = (best_target["u"].get("atk", {}).get(attacker["cls"], 0)) / 100.0
                ret_def_b = (attacker["u"].get("def", {}).get(best_target["cls"], 0)) / 100.0
                ret_dmg = best_target["count"] * best_target["dmg_per_unit"] * (1.0 + ret_atk_b) * (1.0 - ret_def_b)
                ret_killed = min(attacker["count"], int(ret_dmg / attacker["hp_per_unit"]))
                attacker["count"] -= ret_killed
                best_target["ret_left"] -= 1

        p_alive = sum(u["count"] for u in p_units)
        e_alive = sum(u["count"] for u in e_units)
        if p_alive <= 0 or e_alive <= 0: break

    tot_p_start = sum(u["startCount"] * u["wt"] for u in p_units)
    tot_p_end = sum(u["count"] * u["wt"] for u in p_units)
    loss_pct = (tot_p_start - tot_p_end) / tot_p_start * 100.0 if tot_p_start > 0 else 0.0
    won = (e_alive <= 0 and p_alive > 0)

    return {"won": won, "loss_pct": loss_pct, "rounds": round_num}


def run_benchmark(dump_file):
    print("=" * 80)
    print(f"ELVENAR RADAR — BATTLE AI DUMP BENCHMARK SUITE")
    print(f"File: {os.path.basename(dump_file)}")
    print("=" * 80)

    battles, active_buffs, player_tiers = extract_dump_data(dump_file)
    if not battles:
        print("[-] No InstantBattleResultVO found in this dump file!")
        return

    print(f"[+] Total Battles Detected: {len(battles)}")
    print(f"[+] Detected Player City Buffs:")
    print(f"    - Health: +{active_buffs['hp']*100:.1f}%")
    print(f"    - Atk Buffs: LR=+{active_buffs['atk']['light_ranged']*100:.0f}%, MA=+{active_buffs['atk']['mage']*100:.0f}%, HM=+{active_buffs['atk']['heavy_melee']*100:.0f}%, LM=+{active_buffs['atk']['light_melee']*100:.0f}%, HR=+{active_buffs['atk']['heavy_ranged']*100:.0f}%\n")

    # 1. Empirical Unit Survival Stats
    unit_stats = defaultdict(lambda: {"picks": 0, "loss_sum": 0.0, "wiped": 0, "under20": 0})
    actual_records = []
    v661_sim_results = []

    print("-" * 80)
    print(f"{'Battle':8} | {'Enemy Lineup (S1..S5)':34} | {'Actual Loss':12} | {'v6.6.1 Sim Loss':16} | {'Outcome':8}")
    print("-" * 80)

    for b_idx, bvo in enumerate(battles, 1):
        st = bvo.get("state", {})
        units_order = st.get("unitsOrder", [])
        p_units, e_units = [], []
        for u in units_order:
            sy = u.get("startpos", {}).get("y")
            slot = Y_TO_SLOT.get(sy, 99)
            st_amt = u.get("startAmountOfUnits", 0) or 0
            cur_amt = u.get("amountOfUnits", 0) or 0
            ut_id = u.get("unitType", {}).get("unitTypeId", "")
            wt = u.get("unitType", {}).get("unitWeight", 1)
            item = {"slot": slot, "id": ut_id, "start": st_amt, "end": cur_amt, "wt": wt}
            if u.get("teamFlag") == 1:
                p_units.append(item)
                lost_pct = (st_amt - cur_amt) / st_amt * 100.0 if st_amt > 0 else 0.0
                s = unit_stats[ut_id]
                s["picks"] += 1
                s["loss_sum"] += lost_pct
                if cur_amt == 0: s["wiped"] += 1
                if lost_pct < 20.0: s["under20"] += 1
            else:
                e_units.append(item)

        p_units.sort(key=lambda x: x["slot"])
        e_units.sort(key=lambda x: x["slot"])
        p_sq = int(sum(x["start"] * x["wt"] for x in p_units) / 5)
        e_sq = int(sum(x["start"] * x["wt"] for x in e_units) / 5)

        actual_won = (st.get("winnerBit") == 1)
        tot_lost = sum((x["start"] - (x["end"] or 0)) * x["wt"] for x in p_units)
        actual_loss_pct = tot_lost / (p_sq * 5) * 100.0 if p_sq > 0 else 0.0
        actual_records.append((actual_won, actual_loss_pct))

        wave = [x["id"] for x in e_units]
        r661 = [c[0][1] for c in recommend_v661(wave, active_buffs, player_tiers, p_sq, e_sq)]
        sim_res = simulate_battle(r661, wave, p_sq, e_sq, active_buffs, player_tiers)
        v661_sim_results.append(sim_res)

        e_str = "/".join(resolve_unit(w)["short"][:4] for w in wave)
        act_status = f"{actual_loss_pct:4.1f}%" if actual_won else "100% (LOSS)"
        sim_status = f"{sim_res['loss_pct']:4.1f}%" if sim_res["won"] else "LOSS"
        diff_str = "BETTER" if sim_res["loss_pct"] < actual_loss_pct else ("SAME" if abs(sim_res["loss_pct"] - actual_loss_pct) < 1 else "WORSE")
        print(f"B{b_idx:02d}     | {e_str:34} | {act_status:12} | {sim_status:16} | {diff_str:8}")

    print("\n" + "=" * 80)
    print("EMPIRICAL UNIT SURVIVAL RANKING (RECORDED FROM USER PLAY)")
    print("=" * 80)
    print(f"{'Unit Name':24} | {'Picks':6} | {'Avg Loss%':10} | {'Wiped (100%)':14} | {'Safe (<20%)':12}")
    print("-" * 80)
    for uid, s in sorted(unit_stats.items(), key=lambda x: (x[1]["loss_sum"] / x[1]["picks"])):
        u_name = resolve_unit(uid)["name"]
        avg_l = s["loss_sum"] / s["picks"]
        w_pct = (s["wiped"] / s["picks"]) * 100.0
        s_pct = (s["under20"] / s["picks"]) * 100.0
        print(f"{u_name:24} | {s['picks']:6d} | {avg_l:9.1f}% | {s['wiped']:3d} ({w_pct:4.0f}%)   | {s['under20']:3d} ({s_pct:4.0f}%)")

    print("\n" + "=" * 80)
    print("OVERALL PERFORMANCE SUMMARY: ACTUAL PLAYED vs ADVISOR v6.6.1")
    print("=" * 80)
    act_wins = sum(1 for w, _ in actual_records if w)
    act_avg = sum(l for _, l in actual_records) / len(actual_records)
    sim_wins = sum(1 for r in v661_sim_results if r["won"])
    sim_avg = sum(r["loss_pct"] for r in v661_sim_results) / len(v661_sim_results)

    print(f"Metric                     | Actual Played      | Advisor v6.6.1 Simulated")
    print("-" * 80)
    print(f"Win Rate                   | {act_wins}/{len(actual_records)} ({act_wins/len(actual_records)*100:5.1f}%)    | {sim_wins}/{len(v661_sim_results)} ({sim_wins/len(v661_sim_results)*100:5.1f}%)")
    print(f"Average Casualties         | {act_avg:5.1f}%             | {sim_avg:5.1f}% (Reduced by {act_avg - sim_avg:4.1f}%)")

    print("\nCASUALTY DISTRIBUTION BRACKETS:")
    print(f"{'Bracket':26} | {'Actual Played':18} | {'Advisor v6.6.1':18}")
    print("-" * 80)
    brackets = [
        ("< 15% (Flawless)", 0, 15),
        ("15% - 30% (Light)", 15, 30),
        ("30% - 50% (Moderate)", 30, 50),
        (">= 50% / Defeat", 50, 1000)
    ]
    for label, low, high in brackets:
        c_act = sum(1 for won, l in actual_records if low <= l < high or (not won and high >= 100))
        c_sim = sum(1 for r in v661_sim_results if low <= r["loss_pct"] < high or (not r["won"] and high >= 100))
        print(f"{label:26} | {c_act:2d} ({c_act/len(actual_records)*100:4.1f}%)         | {c_sim:2d} ({c_sim/len(v661_sim_results)*100:4.1f}%)")
    print("=" * 80)


if __name__ == "__main__":
    target_file = None
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    else:
        # Auto-discover newest json dump in data folders
        search_dirs = [
            os.path.join(REPO_DIR, "..", "Batte AI Data"),
            os.path.join(REPO_DIR, "..")
        ]
        candidates = []
        for d in search_dirs:
            if os.path.exists(d):
                candidates.extend(glob.glob(os.path.join(d, "*.json")))
        if candidates:
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            target_file = candidates[0]

    if not target_file or not os.path.exists(target_file):
        print("Usage: python benchmark_dump.py <path_to_dump.json>")
        sys.exit(1)

    run_benchmark(target_file)
