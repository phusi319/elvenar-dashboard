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
import math
from collections import defaultdict, deque

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INDEX_HTML_PATH = os.path.join(REPO_DIR, "index.html")

# True Elvenar Hex map vertical coordinate mapping
# Top (y=2): Slot 4 | Upper-Mid (y=3): Slot 2 | Center (y=4): Slot 1 | Lower-Mid (y=5): Slot 3 | Bottom (y=6): Slot 5
SLOT_Y = [4, 3, 5, 2, 6]
Y_TO_SLOT = {4: 1, 3: 2, 5: 3, 2: 4, 6: 5}

GRID_W, GRID_H = 8, 9

def to_cube(x, y):
    q = x - ((y - (y & 1)) // 2)
    r = y
    return (q, r, -q - r)

def hex_dist(a, b):
    qa, ra, sa = to_cube(a[0], a[1])
    qb, rb, sb = to_cube(b[0], b[1])
    return max(abs(qa - qb), abs(ra - rb), abs(sa - sb))

def hex_neighbors(x, y):
    if y % 2 == 0:
        deltas = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1)]
    else:
        deltas = [(-1, 0), (1, 0), (0, -1), (0, 1), (1, -1), (1, 1)]
    return [(x + dx, y + dy) for dx, dy in deltas if 0 <= x + dx < GRID_W and 0 <= y + dy < GRID_H]

def bfs_reachable(start, max_mv, blocked_set):
    reach = {start: 0}
    q = deque([start])
    while q:
        curr = q.popleft()
        steps = reach[curr]
        if steps >= max_mv:
            continue
        for n in hex_neighbors(curr[0], curr[1]):
            if n not in reach and n not in blocked_set:
                reach[n] = steps + 1
                q.append(n)
    return reach

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
    latest_effects = None
    active_buffs = {
        "hp": 0.0,
        "atk": {"light_melee": 0.0, "light_ranged": 0.0, "mage": 0.0, "heavy_melee": 0.0, "heavy_ranged": 0.0},
        "spire_atk": {"light_melee": 0.0, "light_ranged": 0.0, "mage": 0.0, "heavy_melee": 0.0, "heavy_ranged": 0.0}
    }
    player_tiers = [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 3, 2, 2]

    def walk(d):
        nonlocal latest_effects
        if isinstance(d, dict):
            if d.get("__class__") == "InstantBattleResultVO":
                battles.append(d)
            if d.get("requestClass") == "EffectsService" and d.get("requestMethod") == "update" and isinstance(d.get("responseData"), list):
                latest_effects = d.get("responseData")
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

    # Parse EffectsService.update if detected
    if latest_effects:
        aw_atk_scale = [0, 5, 7.5, 10, 12.5, 15, 18, 20, 21.5, 23, 25, 28, 30, 31.5, 33, 35, 37.5, 38.5, 39, 40, 40.5, 41.5, 42, 42.5, 43, 43.5, 44, 44.5, 45, 45.5, 46, 47, 47.5, 48, 48.5, 50, 60]
        aw_hp_scale  = [0, 3, 5, 7, 9, 11, 13, 14, 15, 16.5, 18, 20.5, 21.5, 23, 24, 25, 27, 27.5, 28, 28.5, 29, 30, 30.3, 30.6, 30.9, 31.2, 31.8, 32.1, 32.4, 32.7, 33, 33.5, 34, 34.5, 35, 36, 40]
        hp_pct = 0.0
        lm_pct, lr_pct, ma_pct, hm_pct, hr_pct = 0.0, 0.0, 0.0, 0.0, 0.0
        spire_lm, spire_lr, spire_ma, spire_hm, spire_hr = 0.0, 0.0, 0.0, 0.0, 0.0
        for ef in latest_effects:
            if not ef:
                continue
            cid = int(ef.get("confId") or 0)
            lvl = min(36, max(0, int(ef.get("level") or 0)))
            stg = max(0, int(ef.get("stage") or 0))
            is_spire = (ef.get("owner") == "spire" or ef.get("type") == "spire" or (711 <= cid <= 715))
            if is_spire:
                if cid == 711: spire_lm += 15.0
                elif cid == 712: spire_lr += 15.0
                elif cid == 713: spire_ma += 15.0
                elif cid == 714: spire_hm += 15.0
                elif cid == 715: spire_hr += 15.0
                continue
            if cid == 2045: hp_pct += (aw_hp_scale[lvl] if lvl < len(aw_hp_scale) else 0)
            elif cid == 5019: hp_pct += 50.0
            elif cid == 5002: hp_pct += 25.0
            elif cid == 5016:
                phx = (stg * 5.0) if stg > 0 else 50.0
                lm_pct += phx; lr_pct += phx; ma_pct += phx; hm_pct += phx; hr_pct += phx
            elif cid == 2123: lm_pct += (aw_atk_scale[lvl] if lvl < len(aw_atk_scale) else 0)
            elif cid == 2043: lr_pct += (aw_atk_scale[lvl] if lvl < len(aw_atk_scale) else 0)
            elif cid == 2103: ma_pct += (aw_atk_scale[lvl] if lvl < len(aw_atk_scale) else 0)
            elif cid == 2082: hm_pct += (aw_atk_scale[lvl] if lvl < len(aw_atk_scale) else 0)
            elif cid == 2112: hr_pct += (aw_atk_scale[lvl] if lvl < len(aw_atk_scale) else 0)
            elif cid == 5001: ma_pct += 50.0
            elif cid == 5003: lr_pct += 50.0
            elif cid == 5029: lm_pct += 75.0
            elif cid == 5030: hm_pct += 75.0
            elif cid == 5031: hr_pct += 50.0
            elif cid == 5079: hm_pct += 50.0

        active_buffs["hp"] = hp_pct / 100.0
        active_buffs["atk"] = {
            "light_melee": lm_pct / 100.0,
            "light_ranged": lr_pct / 100.0,
            "mage": ma_pct / 100.0,
            "heavy_melee": hm_pct / 100.0,
            "heavy_ranged": hr_pct / 100.0
        }
        active_buffs["spire_atk"] = {
            "light_melee": spire_lm / 100.0,
            "light_ranged": spire_lr / 100.0,
            "mage": spire_ma / 100.0,
            "heavy_melee": spire_hm / 100.0,
            "heavy_ranged": spire_hr / 100.0
        }

    # Extract military buffs from battle packets if present and hp not already found
    if battles and active_buffs["hp"] == 0:
        st = battles[0].get("state", {})
        for u in st.get("unitsOrder", []):
            if u.get("teamFlag") == 1:
                ut = u.get("unitType", {})
                start_hp = u.get("startHitpoints", 0)
                base_hp = ut.get("hitpoints", 0)
                if base_hp > 0 and start_hp > base_hp:
                    active_buffs["hp"] = round((start_hp - base_hp) / base_hp, 3)
                    break

    # Defaults if not specifically detected (Pure City / Tournament Buffs)
    if active_buffs["hp"] == 0:
        active_buffs["hp"] = 0.775
    if sum(active_buffs["atk"].values()) == 0:
        active_buffs["atk"] = {
            "light_melee": 0.73,
            "light_ranged": 0.89,
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
    mitigation_bonus = (def_bonus * 42.0) if def_bonus >= 0.40 else (def_bonus * 18.0)

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


def recommend_heuristic(wave, active_buffs, player_tiers, p_sq=25000, e_sq=25000):
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
                elif dy == 1: sw = 0.42 if reach >= 8 else (0.34 if (rng >= 3 or mv >= 4) else 0.18)
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

                    if is_barracks_dual and e_unit["cls"] in other_countered_cls and not (p_unit["cls"] == "mage" and w_ctx["hasMistWalker"]):
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

            if is_barracks_dual and any(w_ctx["clsCounts"].get(c, 0) > 0 for c in other_countered_cls) and not (p_unit["cls"] == "mage" and w_ctx["hasMistWalker"]):
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


OBSTACLE_PRESETS = [
    [(3, 4), (4, 4)],
    [(3, 3), (4, 5)],
    [(3, 5), (4, 3)],
    [(2, 4), (5, 4)],
    [(3, 2), (3, 4), (4, 6)],
    [(4, 2), (4, 4), (3, 6)],
    [(2, 3), (4, 4), (5, 5)],
    [(2, 5), (3, 4), (5, 3)],
    [(3, 3), (3, 5), (4, 4)],
    [(4, 3), (4, 5), (3, 4)],
    [(2, 2), (3, 4), (4, 4), (5, 6)],
    [(2, 6), (3, 4), (4, 4), (5, 2)],
    [(3, 1), (3, 4), (4, 4), (4, 7)],
    [(2, 4), (3, 3), (4, 5), (5, 4)],
    [(2, 4), (3, 5), (4, 3), (5, 4)],
]


def simulate_battle(player_unit_keys, enemy_unit_ids, player_squad_size, enemy_squad_size, active_buffs, player_tiers=None, obstacle_set=None, initial_counts=None):
    active_buffs = active_buffs or {"hp": 0.0, "atk": {}}
    DMG_EXPECTED_MULT = 1.07
    RETALIATION_MULT = 0.50

    p_units = []
    for i in range(5):
        pkey = player_unit_keys[i]
        u = resolve_unit(pkey, player_tiers)
        hp_mult = 1.0 + active_buffs.get("hp", 0.0)
        atk_mult = 1.0 + active_buffs.get("atk", {}).get(u["cls"], 0)
        wt = u.get("wt", 1)
        full_count = max(1, int(player_squad_size / wt))
        count = initial_counts[i] if (initial_counts is not None and i < len(initial_counts) and initial_counts[i] is not None) else full_count
        hp_per_unit = u["hp"] * hp_mult
        p_units.append({
            "slot": i + 1, "x": 0, "y": SLOT_Y[i], "team": 1, "id": f"P{i+1}", "name": u["short"],
            "cls": u["cls"], "u": u, "startCount": full_count, "count": count,
            "hp_per_unit": hp_per_unit, "dmg_per_unit": (u["dmg"] * atk_mult),
            "hp_pool": count * hp_per_unit,
            "wt": wt, "init": u.get("init", 10), "rng": u.get("rng", 1), "mv": u.get("mv", 2),
            "ret_max": u.get("ret", 0), "ret_left": u.get("ret", 0),
            "atk_debuff": {"val": 0.0, "dur": 0},
            "def_debuff": {"val": 0.0, "dur": 0}
        })

    e_units = []
    for i in range(5):
        eid = enemy_unit_ids[i]
        u = resolve_unit(eid, player_tiers)
        wt = u.get("wt", 1)
        count = max(1, int(enemy_squad_size / wt))
        hp_per_unit = u["hp"]
        e_units.append({
            "slot": i + 1, "x": 7, "y": SLOT_Y[i], "team": 2, "id": f"E{i+1}", "name": u["short"],
            "cls": u["cls"], "u": u, "startCount": count, "count": count,
            "hp_per_unit": hp_per_unit, "dmg_per_unit": u["dmg"],
            "hp_pool": count * hp_per_unit,
            "wt": wt, "init": u.get("init", 10), "rng": u.get("rng", 1), "mv": u.get("mv", 2),
            "ret_max": u.get("ret", 0), "ret_left": u.get("ret", 0),
            "atk_debuff": {"val": 0.0, "dur": 0},
            "def_debuff": {"val": 0.0, "dur": 0}
        })

    def calc_eff_mult(attacker, target):
        atk_b = (attacker["u"].get("atk", {}).get(target["cls"], 0)) / 100.0
        def_b = (target["u"].get("def", {}).get(attacker["cls"], 0)) / 100.0
        a_deb = attacker["atk_debuff"]["val"] / 100.0
        d_deb = target["def_debuff"]["val"] / 100.0
        return (1.0 + atk_b) * (1.0 + a_deb) * (1.0 - def_b) * (1.0 - d_deb)

    for round_num in range(1, 16):
        if round_num > 1:
            for u in p_units + e_units:
                if u["atk_debuff"]["dur"] > 0:
                    u["atk_debuff"]["dur"] -= 1
                    if u["atk_debuff"]["dur"] <= 0:
                        u["atk_debuff"]["val"] = 0.0
                if u["def_debuff"]["dur"] > 0:
                    u["def_debuff"]["dur"] -= 1
                    if u["def_debuff"]["dur"] <= 0:
                        u["def_debuff"]["val"] = 0.0

        for u in p_units + e_units:
            u["ret_left"] = u["ret_max"]

        all_units = [u for u in p_units + e_units if u["count"] > 0]
        all_units.sort(key=lambda u: (u["init"], 1 if u["team"] == 1 else 0, u["slot"]), reverse=True)

        for attacker in all_units:
            if attacker["count"] <= 0: continue
            targets = [u for u in (e_units if attacker["team"] == 1 else p_units) if u["count"] > 0]
            if not targets: break

            start = (attacker["x"], attacker["y"])
            blocked = {(u["x"], u["y"]) for u in p_units + e_units if u["count"] > 0 and u["id"] != attacker["id"]}
            if obstacle_set:
                for obs in obstacle_set:
                    blocked.add((obs[0], obs[1]))
            reach_cells = bfs_reachable(start, attacker["mv"], blocked)

            cand_targets = []
            for tgt in targets:
                tpos = (tgt["x"], tgt["y"])
                valid_cells = [c for c in reach_cells if hex_dist(c, tpos) <= attacker["rng"]]
                if valid_cells:
                    min_steps = min(reach_cells[c] for c in valid_cells)
                    if attacker["rng"] > 1:
                        home_sign = 1 if attacker["team"] == 1 else -1
                        best_c = min(valid_cells, key=lambda c: (-hex_dist(c, tpos), home_sign * c[0], reach_cells[c]))
                    else:
                        best_c = min(valid_cells, key=lambda c: (reach_cells[c], abs(c[1] - start[1])))
                    cand_targets.append((tgt, best_c, min_steps))

            if cand_targets:
                best_t = None
                best_pos = None
                best_score = -999999.0
                for tgt, best_c, min_steps in cand_targets:
                    em = calc_eff_mult(attacker, tgt)
                    edmg = attacker["count"] * attacker["dmg_per_unit"] * em * DMG_EXPECTED_MULT
                    kr = min(1.0, edmg / max(1.0, tgt["hp_pool"]))
                    d_now = hex_dist(start, (tgt["x"], tgt["y"]))
                    fb = 0.0
                    if attacker["team"] == 2:
                        bhp = (tgt["hp_per_unit"] / (1.0 + active_buffs["hp"])) / tgt["wt"]
                        if bhp < 120:
                            fb = (120.0 - bhp) * 0.8
                    score = ((em - 1.0) * 100.0) + (kr * 45.0) - (min_steps * 35.0) - (d_now * 12.0) + fb
                    if score > best_score:
                        best_score = score
                        best_t = tgt
                        best_pos = best_c

                attacker["x"], attacker["y"] = best_pos
                eff_mult = calc_eff_mult(attacker, best_t)
                dealt_dmg = attacker["count"] * attacker["dmg_per_unit"] * eff_mult * DMG_EXPECTED_MULT
                best_t["hp_pool"] = max(0.0, best_t["hp_pool"] - dealt_dmg)
                best_t["count"] = math.ceil(best_t["hp_pool"] / best_t["hp_per_unit"]) if best_t["hp_pool"] > 0 else 0

                if best_t["count"] > 0:
                    for ab in attacker["u"].get("ab", []):
                        ab_type = ab.get("t")
                        ab_val = float(ab.get("v", 0))
                        ab_dur = int(ab.get("d", 1))
                        if ab_type == "attack" and ab_val < 0:
                            best_t["atk_debuff"] = {"val": ab_val, "dur": ab_dur}
                        elif ab_type == "defense" and ab_val < 0:
                            best_t["def_debuff"] = {"val": ab_val, "dur": ab_dur}

                if best_t["count"] > 0 and best_t["ret_left"] > 0 and hex_dist((attacker["x"], attacker["y"]), (best_t["x"], best_t["y"])) <= best_t["rng"]:
                    ret_eff_mult = calc_eff_mult(best_t, attacker)
                    ret_dmg = best_t["count"] * best_t["dmg_per_unit"] * ret_eff_mult * DMG_EXPECTED_MULT * RETALIATION_MULT
                    attacker["hp_pool"] = max(0.0, attacker["hp_pool"] - ret_dmg)
                    attacker["count"] = math.ceil(attacker["hp_pool"] / attacker["hp_per_unit"]) if attacker["hp_pool"] > 0 else 0
                    best_t["ret_left"] -= 1
            else:
                want = min(targets, key=lambda tgt: (hex_dist(start, (tgt["x"], tgt["y"])), tgt["slot"]))
                next_pos = min(reach_cells.keys(), key=lambda c: (hex_dist(c, (want["x"], want["y"])), reach_cells[c], abs(c[1] - start[1])))
                attacker["x"], attacker["y"] = next_pos
                continue

        p_alive = sum(u["count"] for u in p_units)
        e_alive = sum(u["count"] for u in e_units)
        if p_alive <= 0 or e_alive <= 0: break

    tot_p_start = sum(u["startCount"] * u["wt"] for u in p_units)
    tot_p_end = sum(u["count"] * u["wt"] for u in p_units)
    loss_pct = (tot_p_start - tot_p_end) / tot_p_start * 100.0 if tot_p_start > 0 else 0.0
    won = (e_alive <= 0 and p_alive > 0)

    return {"won": won, "loss_pct": loss_pct, "rounds": round_num, "end_counts": [u["count"] for u in p_units]}


def simulate_multi_wave(player_unit_keys, waves, player_squad_size, enemy_squad_size, active_buffs, player_tiers=None, obstacle_set=None):
    if not waves:
        return {"won": True, "loss_pct": 0.0, "rounds": 0, "end_counts": [0] * 5}
    if len(waves) == 1:
        return simulate_battle(player_unit_keys, waves[0], player_squad_size, enemy_squad_size, active_buffs, player_tiers, obstacle_set=obstacle_set)

    tot_p_start = 0
    for i in range(5):
        u = resolve_unit(player_unit_keys[i], player_tiers)
        wt = u.get("wt", 1)
        cnt = max(1, int(player_squad_size / wt))
        tot_p_start += cnt * wt

    cur_counts = None
    last_res = None
    total_rounds = 0
    for w in waves:
        res = simulate_battle(player_unit_keys, w, player_squad_size, enemy_squad_size, active_buffs, player_tiers, obstacle_set=obstacle_set, initial_counts=cur_counts)
        last_res = res
        total_rounds += res["rounds"]
        if not res["won"]:
            return {"won": False, "loss_pct": 100.0, "rounds": total_rounds, "end_counts": [0] * 5}
        cur_counts = res.get("end_counts", [0] * 5)

    tot_p_end = sum(cur_counts[i] * resolve_unit(player_unit_keys[i], player_tiers).get("wt", 1) for i in range(5))
    overall_loss_pct = (tot_p_start - tot_p_end) / tot_p_start * 100.0 if tot_p_start > 0 else 0.0
    return {"won": True, "loss_pct": round(overall_loss_pct, 1), "rounds": total_rounds, "end_counts": cur_counts}


def simulate_battle_monte_carlo(player_unit_keys, enemy_unit_ids, player_squad_size=1000, enemy_squad_size=1500, active_buffs=None, player_tiers=None):
    losses = []
    wins = 0
    is_multi_wave = isinstance(enemy_unit_ids, list) and len(enemy_unit_ids) > 0 and isinstance(enemy_unit_ids[0], list)
    for obs in OBSTACLE_PRESETS:
        res = simulate_multi_wave(player_unit_keys, enemy_unit_ids, player_squad_size, enemy_squad_size, active_buffs, player_tiers, obstacle_set=obs) if is_multi_wave else simulate_battle(player_unit_keys, enemy_unit_ids, player_squad_size, enemy_squad_size, active_buffs, player_tiers, obstacle_set=obs)
        losses.append(res["loss_pct"])
        if res["won"]:
            wins += 1
    losses.sort()
    mean_loss = round(sum(losses) / len(losses), 1)
    p90_loss = round(losses[13], 1)
    win_rate = round(wins * 100.0 / len(OBSTACLE_PRESETS), 1)
    return {
        "mean_loss": mean_loss,
        "p90_loss": p90_loss,
        "win_rate": win_rate,
        "losses": losses
    }


def recommend_v70(waves_or_wave, active_buffs, player_tiers=None, player_squad_size=25000, enemy_squad_size=25000):
    if not waves_or_wave:
        return []
    if isinstance(waves_or_wave[0], list):
        waves = waves_or_wave
        first_wave = waves[0]
    else:
        waves = [waves_or_wave]
        first_wave = waves_or_wave

    p_sq = player_squad_size or 25000
    e_sq = enemy_squad_size or 25000

    # Stage 1: Heuristic Slot Scoring
    heuristic_slots = recommend_heuristic(first_wave, active_buffs, player_tiers, p_sq, e_sq)
    slot_score_map = [{c[1]: c[0] for c in heuristic_slots[s]} for s in range(5)]

    # Strict Slot-Counter Eligibility: Top candidates with score > -10.0 (up to 6 valid counters per enemy class)
    valid_slot_keys = []
    for s in range(5):
        v_keys = [c[1] for c in heuristic_slots[s][:6] if c[0] > -10.0]
        if not v_keys:
            v_keys = [heuristic_slots[s][0][1]]
        valid_slot_keys.append(v_keys)

    # Candidate Lineup Generation (Strictly Counter-Compliant)
    top1 = [heuristic_slots[s][0][1] for s in range(5)]
    top2 = [valid_slot_keys[s][min(1, len(valid_slot_keys[s]) - 1)] for s in range(5)]

    cand_lineups = [tuple(top1), tuple(top2)]

    for s in range(5):
        for v_key in valid_slot_keys[s][1:]:
            var_L = list(top1)
            var_L[s] = v_key
            cand_lineups.append(tuple(var_L))

    # Cohesive Counter Lineups: group slots using the same unit ONLY where that unit is a valid Top-3 counter
    for u in PLAYER_UNIT_KEYS:
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

    # Stage 2: Full-Team Simulation Re-Ranking
    eval_cache = {}
    def eval_lineup(L):
        t = tuple(L)
        if t in eval_cache:
            return eval_cache[t]
        sim = simulate_multi_wave(list(L), waves, p_sq, e_sq, active_buffs, player_tiers)
        h_avg = sum(slot_score_map[s].get(L[s], 0.0) for s in range(5)) / 5.0
        stock_pen = 5000.0 if any(slot_score_map[s].get(L[s], 0.0) < -300.0 for s in range(5)) else 0.0
        non_counter_pen = 2000.0 if any(L[s] not in valid_slot_keys[s] for s in range(5)) else 0.0
        defeat_pen = 0.0 if sim["won"] else 1000.0
        obj = stock_pen + non_counter_pen + defeat_pen + sim["loss_pct"] - (h_avg * 0.15)
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

    # 1-Pass Coordinate Polish (Strictly within valid_slot_keys[s])
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

    # Stage 3: Simulation-Ranked 1-Slot Swap Alternatives (Backup #2 and #3)
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
                swap_ranked.append((swap_obj, swap_sim["loss_pct"], swap_sim["won"], cand_item))

        # Sort backup candidates by 1-slot swap simulation objective (lowest loss / won first)
        swap_ranked.sort(key=lambda x: x[0])

        ranked_keys = {best_key}.union(other_valid_keys)
        remaining_cands = [c for c in heuristic_slots[s] if c[1] not in ranked_keys]

        slot_cands = [best_cand] + [item[3] for item in swap_ranked] + remaining_cands
        final_slots.append(slot_cands)

    return final_slots


recommend_v661 = recommend_v70
recommend_v652 = recommend_v70


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
    actual_sim_results = []
    v661_sim_results = []

    print("-" * 105)
    print(f"{'Battle':8} | {'Enemy Lineup (S1..S5)':28} | {'Actual Real':13} | {'Actual Sim':13} | {'Advisor Sim':13} | {'Fair Outcome':18}")
    print("-" * 105)

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
        actual_p_keys = [x["id"] for x in p_units]
        actual_sim = simulate_battle(actual_p_keys, wave, p_sq, e_sq, active_buffs, player_tiers)
        actual_sim_results.append(actual_sim)

        r661 = [c[0][1] for c in recommend_v661(wave, active_buffs, player_tiers, p_sq, e_sq)]
        advisor_sim = simulate_battle(r661, wave, p_sq, e_sq, active_buffs, player_tiers)
        v661_sim_results.append(advisor_sim)

        e_str = "/".join(resolve_unit(w)["short"][:4] for w in wave)
        act_status = f"{actual_loss_pct:4.1f}%" if actual_won else "100% (LOSS)"
        act_sim_status = f"{actual_sim['loss_pct']:4.1f}%" if actual_sim["won"] else "LOSS"
        adv_sim_status = f"{advisor_sim['loss_pct']:4.1f}%" if advisor_sim["won"] else "LOSS"

        # Fair Outcome: Advisor Sim vs Actual Sim
        delta = actual_sim["loss_pct"] - advisor_sim["loss_pct"]
        if advisor_sim["won"] and not actual_sim["won"]:
            diff_str = "SAVED (WIN)"
        elif not advisor_sim["won"] and actual_sim["won"]:
            diff_str = "DEFEAT (WORSE)"
        elif delta > 1.0:
            diff_str = f"BETTER (+{delta:.1f}%)"
        elif delta < -1.0:
            diff_str = f"WORSE ({delta:.1f}%)"
        else:
            diff_str = "SAME"
        print(f"B{b_idx:02d}     | {e_str:28} | {act_status:13} | {act_sim_status:13} | {adv_sim_status:13} | {diff_str:18}")

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

    print("\n" + "=" * 90)
    print("OVERALL PERFORMANCE SUMMARY: ACTUAL PLAYED vs ACTUAL SIMULATED vs ADVISOR v6.6.1")
    print("=" * 90)
    act_wins = sum(1 for w, _ in actual_records if w)
    act_avg = sum(l for _, l in actual_records) / len(actual_records)

    act_sim_wins = sum(1 for r in actual_sim_results if r["won"])
    act_sim_avg = sum(r["loss_pct"] for r in actual_sim_results) / len(actual_sim_results)

    sim_wins = sum(1 for r in v661_sim_results if r["won"])
    sim_avg = sum(r["loss_pct"] for r in v661_sim_results) / len(v661_sim_results)

    sim_fidelity_mae = sum(abs(actual_records[i][1] - actual_sim_results[i]["loss_pct"]) for i in range(len(actual_records))) / len(actual_records)
    fair_delta = act_sim_avg - sim_avg

    print(f"{'Metric':26} | {'Actual Played (Real)':22} | {'Actual Lineup (Sim)':22} | {'Advisor v6.6.1 (Sim)':22}")
    print("-" * 90)
    print(f"{'Win Rate':26} | {act_wins}/{len(actual_records)} ({act_wins/len(actual_records)*100:5.1f}%)          | {act_sim_wins}/{len(actual_sim_results)} ({act_sim_wins/len(actual_sim_results)*100:5.1f}%)          | {sim_wins}/{len(v661_sim_results)} ({sim_wins/len(v661_sim_results)*100:5.1f}%)")
    print(f"{'Average Casualties':26} | {act_avg:5.1f}%                 | {act_sim_avg:5.1f}%                 | {sim_avg:5.1f}%")
    print("-" * 90)
    print(f"[*] Simulator Fidelity MAE (|Actual Sim - Actual Real|): {sim_fidelity_mae:.2f} pts")
    print(f"[*] Fair Sim-vs-Sim Delta (Actual Sim Avg - Advisor Sim Avg): {fair_delta:+.2f} pts {'(Advisor Better)' if fair_delta > 0 else '(Advisor Worse)'}")

    print("\nCASUALTY DISTRIBUTION BRACKETS:")
    print(f"{'Bracket':26} | {'Actual Played (Real)':22} | {'Actual Lineup (Sim)':22} | {'Advisor v6.6.1 (Sim)':22}")
    print("-" * 90)
    brackets = [
        ("< 15% (Flawless)", 0, 15),
        ("15% - 30% (Light)", 15, 30),
        ("30% - 50% (Moderate)", 30, 50),
        (">= 50% / Defeat", 50, 1000)
    ]
    for label, low, high in brackets:
        c_act = sum(1 for won, l in actual_records if low <= l < high or (not won and high >= 100))
        c_act_sim = sum(1 for r in actual_sim_results if low <= r["loss_pct"] < high or (not r["won"] and high >= 100))
        c_sim = sum(1 for r in v661_sim_results if low <= r["loss_pct"] < high or (not r["won"] and high >= 100))
        print(f"{label:26} | {c_act:2d} ({c_act/len(actual_records)*100:4.1f}%)               | {c_act_sim:2d} ({c_act_sim/len(actual_sim_results)*100:4.1f}%)               | {c_sim:2d} ({c_sim/len(v661_sim_results)*100:4.1f}%)")
    print("=" * 90)


DEFAULT_DUMP_FILES = [
    os.path.join(REPO_DIR, "..", "Batte AI Data", "(tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json"),
    os.path.join(REPO_DIR, "..", "Batte AI Data", "elvenar_debug_dump_live_2026-11-06T08-08-29-735Z.json"),
    os.path.join(REPO_DIR, "..", "elvenar_debug_dump_live_2026-11-05T17-50-42-275Z.json"),
    os.path.join(REPO_DIR, "..", "elvenar_debug_dump_live_2026-11-05T18-54-06-095Z.json"),
]


def load_all_dump_battles():
    out = []
    for p in DEFAULT_DUMP_FILES:
        p = os.path.normpath(p)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                dump = json.load(f)
        except Exception:
            continue

        def walk(d):
            if isinstance(d, dict):
                if d.get("__class__") == "InstantBattleResultVO" and d.get("state", {}).get("stepHistory"):
                    out.append(d)
                for v in d.values():
                    walk(v)
            elif isinstance(d, list):
                for x in d:
                    walk(x)

        for e in dump:
            data = e.get("payload") or e.get("data")
            if not data:
                continue
            try:
                walk(json.loads(data) if isinstance(data, str) else data)
            except Exception:
                pass
    return out


def run_all_benchmark():
    battles = load_all_dump_battles()
    print("=" * 105)
    print("ELVENAR RADAR — COMPREHENSIVE 40-BATTLE BENCHMARK SUITE (PHASE P5)")
    print(f"Total Battles Loaded: {len(battles)} (Train: 30, Holdout: 10)")
    print("=" * 105)

    if not battles:
        print("[-] Error: No dump battles found!")
        return

    city_atk = {"light_melee": .73, "light_ranged": 0.89, "mage": .90, "heavy_melee": .83, "heavy_ranged": .60}

    results = []
    print(f"{'#':3} | {'Split':7} | {'Enemy Lineup (S1..S5)':28} | {'Actual Real':12} | {'Actual Sim':12} | {'Advisor Sim':12} | {'Fair Outcome':16}")
    print("-" * 105)

    for b_idx, b in enumerate(battles):
        split = "TRAIN" if b_idx < 30 else "HOLDOUT"
        st = b.get("state", {})
        units_order = st.get("unitsOrder", [])
        p_units = sorted([u for u in units_order if u.get("teamFlag") == 1], key=lambda u: Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))
        e_units = sorted([u for u in units_order if u.get("teamFlag") == 2], key=lambda u: Y_TO_SLOT.get(u.get("startpos", {}).get("y", 0), 99))

        p_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in p_units) / 5)
        e_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in e_units) / 5)
        buffs = {"hp": p_units[0]["startHitpoints"] / p_units[0]["unitType"]["hitpoints"] - 1, "atk": city_atk}

        actual_won = (st.get("winnerBit") == 1)
        tot_lost = sum((u["startAmountOfUnits"] - (u.get("amountOfUnits", 0) or 0)) * u["unitType"]["unitWeight"] for u in p_units)
        actual_loss_pct = tot_lost / (p_sq * 5) * 100.0 if p_sq > 0 else 0.0

        wave = [u["unitType"]["unitTypeId"] for u in e_units]
        actual_p_keys = [u["unitType"]["unitTypeId"] for u in p_units]

        actual_sim = simulate_battle(actual_p_keys, wave, p_sq, e_sq, buffs, None)
        rec_slots = recommend_v70(wave, buffs, None, p_sq, e_sq)
        rec_lineup = [c[0][1] for c in rec_slots]
        advisor_sim = simulate_battle(rec_lineup, wave, p_sq, e_sq, buffs, None)

        delta = actual_sim["loss_pct"] - advisor_sim["loss_pct"]
        if advisor_sim["won"] and not actual_sim["won"]:
            outcome = "SAVED (WIN)"
        elif not advisor_sim["won"] and actual_sim["won"]:
            outcome = "DEFEAT (WORSE)"
        elif not advisor_sim["won"]:
            outcome = "LOST"
        elif delta > 1.0:
            outcome = f"BETTER (+{delta:.1f}%)"
        elif delta < -1.0:
            outcome = f"WORSE ({delta:.1f}%)"
        else:
            outcome = "SAME"

        e_str = "/".join(resolve_unit(w)["short"][:4] for w in wave)
        act_status = f"{actual_loss_pct:4.1f}%" if actual_won else "100% (LOSS)"
        act_sim_status = f"{actual_sim['loss_pct']:4.1f}%" if actual_sim["won"] else "LOSS"
        adv_sim_status = f"{advisor_sim['loss_pct']:4.1f}%" if advisor_sim["won"] else "LOSS"

        print(f"B{b_idx+1:02d} | {split:7} | {e_str:28} | {act_status:12} | {act_sim_status:12} | {adv_sim_status:12} | {outcome:16}")

        results.append({
            "idx": b_idx,
            "split": split,
            "actual_won": actual_won,
            "actual_loss_pct": actual_loss_pct,
            "actual_sim": actual_sim,
            "advisor_sim": advisor_sim,
            "delta": delta,
            "outcome": outcome
        })

    def print_split_summary(name, subset):
        n = len(subset)
        if n == 0:
            return
        wins = sum(1 for r in subset if r["advisor_sim"]["won"])
        act_sim_wins = sum(1 for r in subset if r["actual_sim"]["won"])
        act_real_wins = sum(1 for r in subset if r["actual_won"])

        act_real_avg = sum(r["actual_loss_pct"] for r in subset) / n
        act_sim_avg = sum(r["actual_sim"]["loss_pct"] for r in subset) / n
        adv_sim_avg = sum(r["advisor_sim"]["loss_pct"] for r in subset) / n

        better_c = sum(1 for r in subset if "BETTER" in r["outcome"])
        saved_c = sum(1 for r in subset if "SAVED" in r["outcome"])
        same_c = sum(1 for r in subset if "SAME" in r["outcome"])
        worse_c = sum(1 for r in subset if "WORSE" in r["outcome"])
        lost_c = sum(1 for r in subset if "LOST" in r["outcome"] or "DEFEAT" in r["outcome"])

        print("\n" + "=" * 90)
        print(f"SPLIT PERFORMANCE SUMMARY: {name} ({n} BATTLES)")
        print("=" * 90)
        print(f"{'Metric':26} | {'Actual Played (Real)':22} | {'Actual Lineup (Sim)':22} | {'Advisor Hybrid (Sim)':22}")
        print("-" * 90)
        print(f"{'Win Rate':26} | {act_real_wins}/{n} ({act_real_wins/n*100:5.1f}%)          | {act_sim_wins}/{n} ({act_sim_wins/n*100:5.1f}%)          | {wins}/{n} ({wins/n*100:5.1f}%)")
        print(f"{'Average Casualties':26} | {act_real_avg:5.1f}%                 | {act_sim_avg:5.1f}%                 | {adv_sim_avg:5.1f}%")
        print("-" * 90)
        print(f"[*] Head-to-Head vs Actual Sim : Better: {better_c} | Saved: {saved_c} | Same: {same_c} | Worse: {worse_c} | Lost: {lost_c}")
        delta_net = act_sim_avg - adv_sim_avg
        print(f"[*] Net Casualty Reduction     : {delta_net:+.2f} pts {'(Advisor Better)' if delta_net > 0 else ''}")

    print_split_summary("ALL", results)
    print_split_summary("TRAIN (Battles 1-30)", results[:30])
    print_split_summary("HOLDOUT (Battles 31-40)", results[30:])


if __name__ == "__main__":
    if "--all" in sys.argv:
        run_all_benchmark()
        sys.exit(0)

    target_file = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
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
        print("Usage: python benchmark_dump.py [--all] [<path_to_dump.json>]")
        sys.exit(1)

    run_benchmark(target_file)
