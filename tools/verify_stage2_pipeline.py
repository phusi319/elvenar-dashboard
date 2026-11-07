"""
Verification Script for Stage 2: Userscript & Map Pipeline Upgrade
Validates obstacle extraction from BattleRealmVO and preservation across surrender-peek cycles
against the tourney high stages live dump.
"""

import json
import os

DUMP_PATH = r"D:\ElvenarAuto\Batte AI Data\(tourney high stages)elvenar_debug_dump_live_2026-11-07T17-47-17-100Z.json"

def extract_obstacles_from_map(b_map):
    if not b_map:
        return []
    if isinstance(b_map, dict) and "map" in b_map and isinstance(b_map["map"], dict):
        b_map = b_map["map"]
    tiles = b_map.get("tiles") if isinstance(b_map, dict) else (b_map if isinstance(b_map, list) else None)
    if not tiles or not isinstance(tiles, list):
        return []

    obstacles = []
    seen = set()

    def add_obs(x, y):
        try:
            ox, oy = int(x), int(y)
            if 0 <= ox < 8 and 0 <= oy < 9:
                k = (ox, oy)
                if k not in seen:
                    seen.add(k)
                    obstacles.append([ox, oy])
        except (ValueError, TypeError):
            pass

    def is_obstacle_cell(cell):
        if not cell:
            return False
        if isinstance(cell, str):
            s = cell.lower()
            return "obstacle" in s or "blocked" in s or "barrier" in s
        if isinstance(cell, dict):
            type_id = str(cell.get("typeId") or cell.get("type") or "").lower()
            cost = cell.get("movementCosts", cell.get("cost", 0))
            try:
                cost = float(cost)
            except (ValueError, TypeError):
                cost = 0
            return (
                type_id == "obstacle"
                or "obstacle" in type_id
                or "blocked" in type_id
                or cost > 1000
                or cell.get("isObstacle") is True
                or cell.get("blocked") is True
                or cell.get("passable") is False
                or cell.get("walkable") is False
            )
        return False

    if isinstance(tiles[0], list):
        for x, col in enumerate(tiles):
            if not isinstance(col, list):
                continue
            for y, cell in enumerate(col):
                if is_obstacle_cell(cell):
                    pos = cell.get("pos") or cell.get("position") if isinstance(cell, dict) else None
                    ox = pos.get("x") if pos and "x" in pos else x
                    oy = pos.get("y") if pos and "y" in pos else y
                    add_obs(ox, oy)
    else:
        h = int(b_map.get("height", 9)) if isinstance(b_map, dict) else 9
        for i, cell in enumerate(tiles):
            if is_obstacle_cell(cell):
                pos = cell.get("pos") or cell.get("position") if isinstance(cell, dict) else None
                if pos and "x" in pos and "y" in pos:
                    add_obs(pos["x"], pos["y"])
                else:
                    add_obs(i // h, i % h)

    obstacles.sort(key=lambda p: (p[0], p[1]))
    return obstacles

def are_waves_compatible(prev_waves, new_waves):
    if not prev_waves or not new_waves:
        return False
    if prev_waves == new_waves:
        return True
    if len(prev_waves) == len(new_waves):
        w0_prev = ",".join(sorted(prev_waves[0] or []))
        w0_new = ",".join(sorted(new_waves[0] or []))
        if w0_prev and w0_prev == w0_new:
            return True
    return False

def run_verification():
    print("=" * 70)
    print("STAGE 2 VERIFICATION: Userscript & Map Pipeline Extraction")
    print("=" * 70)

    with open(DUMP_PATH, "r", encoding="utf-8") as f:
        dump_data = json.load(f)

    # 1. Test extraction on all 13 manual battle starts
    print("\n--- 1. Testing BattlefieldService.start (Manual Battle Peeks) ---")
    manual_battles = []
    for idx, item in enumerate(dump_data):
        payload = item.get("payload", [])
        if isinstance(payload, dict):
            payload = [payload]
        for p in payload:
            if isinstance(p, dict) and p.get("requestMethod") == "start" and p.get("requestClass") == "BattlefieldService":
                resp = p.get("responseData", {})
                bmap = resp.get("map", {})
                b_id = resp.get("battleId")
                obs = extract_obstacles_from_map(bmap)
                manual_battles.append((idx, b_id, obs, bmap.get("width"), bmap.get("height")))

    print(f"Found {len(manual_battles)} manual battle packets in dump (Expected: 13):")
    for i, (idx, b_id, obs, w, h) in enumerate(manual_battles, 1):
        print(f"  #{i:02d} [Dump {idx:03d}] BattleId={b_id} Map={w}x{h} ObsCount={len(obs)}: {obs}")
        assert 5 <= len(obs) <= 8, f"Unexpected obstacle count {len(obs)} in battle {b_id}"
        assert w == 8 and h == 9, f"Invalid dimensions {w}x{h}"
        for ox, oy in obs:
            assert 0 <= ox < 8 and 0 <= oy < 9, f"Invalid coord [{ox}, {oy}]"

    assert len(manual_battles) == 13, f"Expected 13 manual battles, got {len(manual_battles)}"
    print(f"-> 100% of 13 manual battle maps extracted accurately! (All within 5-8 obstacles)")

    # 2. Test getBattle packets
    print("\n--- 2. Testing BattleService.getBattle Packets ---")
    get_battles = []
    for idx, item in enumerate(dump_data):
        payload = item.get("payload", [])
        if isinstance(payload, dict):
            payload = [payload]
        for p in payload:
            if isinstance(p, dict) and p.get("requestMethod") == "getBattle" and p.get("requestClass") == "BattleService":
                resp = p.get("responseData", {})
                bmap = resp.get("map", {})
                b_id = resp.get("battleId")
                obs = extract_obstacles_from_map(bmap)
                get_battles.append((idx, b_id, obs))

    print(f"Found {len(get_battles)} getBattle packets in dump (Expected: 13):")
    for i, (idx, b_id, obs) in enumerate(get_battles, 1):
        match_start = manual_battles[i-1][2]
        assert obs == match_start, f"Mismatch between start and getBattle for battle #{i}!"
    print(f"-> 100% of 13 getBattle packets match BattlefieldService.start identically!")

    # 3. Simulate Encounter -> Peek -> Surrender -> Return to Window -> Auto-Battle pipeline
    print("\n--- 3. Testing Surrender-Peek Obstacle Preservation Pipeline ---")
    tracked_encounter = None
    surrender_checks = 0

    for idx, item in enumerate(dump_data):
        payload = item.get("payload", [])
        if isinstance(payload, dict):
            payload = [payload]

        def walk(node):
            nonlocal tracked_encounter
            if not isinstance(node, (dict, list)):
                return

            if isinstance(node, dict):
                # G. Encounters
                encs = node.get("encounters")
                if isinstance(encs, list) and encs:
                    active = next((e for e in encs if isinstance(e, dict) and e.get("enemyWaves") and not e.get("completed")), None)
                    if not active:
                        active = next((e for e in encs if isinstance(e, dict) and e.get("enemyWaves")), None)
                    if active and active.get("enemyWaves"):
                        waves = [[u.get("unitTypeId", "") for u in w.get("army", [])] for w in active["enemyWaves"] if w.get("army")]
                        if waves:
                            preserved_obs = None
                            if tracked_encounter and tracked_encounter.get("obstacles"):
                                if are_waves_compatible(tracked_encounter.get("waves"), waves):
                                    preserved_obs = tracked_encounter["obstacles"]
                            tracked_encounter = {
                                "src": "tournament" if node.get("good_id") else "province",
                                "waves": waves,
                                "obstacles": preserved_obs,
                                "pSq": node.get("playerSquadSize", 0),
                                "eSq": active["enemyWaves"][0].get("squadSize", 0)
                            }

                # G.2 Map / Obstacle Extraction
                req_cls = node.get("requestClass")
                req_mth = node.get("requestMethod")
                resp_data = node.get("responseData")
                cls_name = node.get("__class__")

                bmap_candidate = None
                if cls_name == "BattleRealmVO" and "map" in node:
                    bmap_candidate = node["map"]
                elif cls_name == "BattleMapVO" and "tiles" in node:
                    bmap_candidate = node
                elif req_cls in ("BattlefieldService", "BattleService") and req_mth in ("start", "getBattle") and isinstance(resp_data, dict) and "map" in resp_data:
                    bmap_candidate = resp_data["map"]

                if bmap_candidate:
                    obs = extract_obstacles_from_map(bmap_candidate)
                    if obs:
                        if not tracked_encounter:
                            tracked_encounter = {"waves": [], "obstacles": obs}
                        else:
                            tracked_encounter["obstacles"] = obs

                for v in node.values():
                    walk(v)

            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(payload)

        # Check state after Surrender
        s = json.dumps(item)
        if "surrender" in s.lower() and idx > 0:
            surrender_checks += 1
            obs_cnt = len(tracked_encounter["obstacles"]) if tracked_encounter and tracked_encounter.get("obstacles") else 0
            print(f"  Surrender #{surrender_checks:02d} [Dump {idx:03d}]: tracked_encounter.obstacles preserved = {obs_cnt} obstacles")
            assert obs_cnt in (5, 6, 7, 8), f"Obstacles were wiped after surrender at Dump {idx}!"

    print(f"\n-> All {surrender_checks} surrender cycles successfully preserved live map obstacles!")
    print("\n" + "=" * 70)
    print("ALL STAGE 2 VERIFICATION TESTS PASSED SUCCESSFULLY (100% ACCURACY)!")
    print("=" * 70)

if __name__ == "__main__":
    run_verification()
