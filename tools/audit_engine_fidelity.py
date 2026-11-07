#!/usr/bin/env python3
"""
Elvenar Radar — Simulator Fidelity Audit (ground-truth from stepHistory)
=======================================================================
Validates the combat simulator against REAL server battle logs contained in
InstantBattleResultVO.state.stepHistory (every move path, target, damage,
attackModifier, kills, retaliation, applied debuffs).

Usage:
    python tools/audit_engine_fidelity.py                 # all *.json in ../../Batte AI Data
    python tools/audit_engine_fidelity.py a.json b.json   # explicit dumps

Sections:
    1. Battle shape (rounds, grid, spawn cells, squad ratio)
    2. Hex geometry (odd-r offset) + movement/range legality
    3. Hidden obstacle evidence (detours not explained by unit blocking)
    4. Retaliation rule (target in range + charge + alive)
    5. Target-selection rule match rate
    6. Debuff / ability application rate
    7. Simulator fidelity: simulate_battle(ACTUAL lineup) vs ACTUAL result
       -> the KPI every roadmap phase must improve (MAE, outcome agreement)
"""
import os, sys, glob, json, math
from collections import Counter, defaultdict, deque

if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import benchmark_dump as bd  # noqa: E402

W, H = 8, 9
CITY_ATK = {"light_melee": .73, "light_ranged": 1.04, "mage": .90, "heavy_melee": .83, "heavy_ranged": .60}
PX = lambda p: (p.get("x", 0), p.get("y", 0))  # server omits zero-valued fields


def to_cube(c):
    x, y = c
    q = x - (y - (y & 1)) // 2
    return q, y, -q - y


def hexdist(a, b):
    a, b = to_cube(a), to_cube(b)
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def neighbors(c):
    x, y = c
    d = [(-1, 0), (1, 0), (0, -1), (0, 1)] + ([(-1, -1), (-1, 1)] if y % 2 == 0 else [(1, -1), (1, 1)])
    return [(x + dx, y + dy) for dx, dy in d if 0 <= x + dx < W and 0 <= y + dy < H]


def bfs_len(start, goal, blocked):
    q, seen = deque([(start, 0)]), {start}
    while q:
        c, d = q.popleft()
        if c == goal:
            return d
        for n in neighbors(c):
            if n not in seen and n not in blocked:
                seen.add(n)
                q.append((n, d + 1))
    return None


def load_battles(paths):
    out = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            dump = json.load(f)

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
        print(f"[+] {os.path.basename(p)}: {len(out)} battles cumulative")
    return out


def hr(t):
    print("\n" + "=" * 90 + "\n" + t + "\n" + "=" * 90)


def replay(b):
    """Yield (step, units, cur_pos_before, start, end, dead_set) while tracking positions & deaths."""
    st = b["state"]
    units = {u["unitId"]: u for u in st["unitsOrder"]}
    cur = {u["unitId"]: PX(u["startpos"]) for u in st["unitsOrder"]}
    amt = {u["unitId"]: u["startAmountOfUnits"] for u in st["unitsOrder"]}
    dead = set()
    for s in st["stepHistory"]:
        uid = s["unitId"]
        start = cur[uid]
        path = [PX(p) for p in s.get("path", [])]
        end = path[-1] if path else start
        yield s, units, dict(cur), start, end, path, set(dead), dict(amt)
        cur[uid] = end
        if "attackedUnitId" in s:
            t = s["attackedUnitId"]
            amt[t] -= s.get("killedUnits", 0)
            if amt[t] <= 0:
                dead.add(t)


def main(paths):
    B = load_battles(paths)
    if not B:
        print("No battles with stepHistory found.")
        return

    hr("1. BATTLE SHAPE")
    rounds = Counter(b["state"]["round"] for b in B)
    ratios = []
    for b in B:
        u = b["state"]["unitsOrder"]
        pw = sum(x["startAmountOfUnits"] * x["unitType"]["unitWeight"] for x in u if x["teamFlag"] == 1)
        ew = sum(x["startAmountOfUnits"] * x["unitType"]["unitWeight"] for x in u if x["teamFlag"] == 2)
        ratios.append(ew / pw)
    print("battles:", len(B), "| final round distribution:", dict(sorted(rounds.items())))
    print(f"enemy/player squad ratio: min {min(ratios):.2f} avg {sum(ratios)/len(ratios):.2f} max {max(ratios):.2f}")
    spawns = Counter((u["teamFlag"], PX(u["startpos"])) for b in B for u in b["state"]["unitsOrder"])
    print("spawn cells:", sorted(spawns))

    hr("2. HEX GEOMETRY (odd-r offset, 8x9) & LEGALITY")
    nb_ok = nb_bad = mv_bad = rng_bad = 0
    for b in B:
        for s, units, cur, start, end, path, dead, amt in replay(b):
            prev = start
            for p in path:
                if p != prev:
                    nb_ok += p in neighbors(prev)
                    nb_bad += p not in neighbors(prev)
                prev = p
            ut = units[s["unitId"]]["unitType"]
            steps = sum(1 for i, p in enumerate(path) if p != (path[i - 1] if i else start))
            mv_bad += steps > ut["movementPoints"]
            if "attackedUnitId" in s:
                rng_bad += hexdist(end, cur[s["attackedUnitId"]]) > ut["range"]
    print(f"path steps are hex-neighbours: OK {nb_ok} BAD {nb_bad} | moves > movementPoints: {mv_bad} | attacks beyond range: {rng_bad}")

    hr("3. HIDDEN OBSTACLE EVIDENCE")
    c = Counter()
    for b in B:
        st = b["state"]
        visited = {PX(u["startpos"]) for u in st["unitsOrder"]} | {PX(u["pos"]) for u in st["unitsOrder"]}
        for s in st["stepHistory"]:
            visited |= {PX(p) for p in s.get("path", [])}
        for s, units, cur, start, end, path, dead, amt in replay(b):
            steps = sum(1 for i, p in enumerate(path) if p != (path[i - 1] if i else start))
            if steps <= hexdist(start, end):
                c["direct moves"] += 1
                continue
            blocked = {cur[o] for o in cur if o != s["unitId"] and o not in dead}
            L = bfs_len(start, end, blocked)
            if L == steps:
                c["detour explained by units"] += 1
            else:
                c["detour UNEXPLAINED (=> static obstacle)"] += 1
    for k, v in c.items():
        print(f"   {k:42} {v}")

    hr("4. RETALIATION RULE")
    rc = Counter()
    for b in B:
        for s, units, cur, start, end, path, dead, amt in replay(b):
            if "attackedUnitId" not in s:
                continue
            t = s["attackedUnitId"]
            tt = units[t]["unitType"]
            in_rng = hexdist(end, cur[t]) <= tt["range"]
            alive = amt[t] - s.get("killedUnits", 0) > 0
            got = s.get("retaliationDamage", -1) > 0
            rc[(in_rng, tt.get("retaliation", 0) > 0, alive, got)] += 1
    print("   (target_in_its_range, target_has_ret, target_survived, retaliated) -> count")
    for k, v in sorted(rc.items()):
        print("   ", k, v)
    melee_only = sum(v for k, v in rc.items() if k[3])
    print(f"   retaliations observed: {melee_only} (simulator currently only models melee rng==1 attackers)")

    hr("5. TARGET SELECTION")
    crit = defaultdict(Counter)
    n = Counter()
    for b in B:
        for s, units, cur, start, end, path, dead, amt in replay(b):
            if "attackedUnitId" not in s:
                continue
            a = units[s["unitId"]]
            at = a["unitType"]
            cands = [o for o in units if units[o]["teamFlag"] != a["teamFlag"] and o not in dead]
            reach = at["movementPoints"] + at["range"]
            rc_ = [o for o in cands if hexdist(start, cur[o]) <= reach] or cands

            def mod(o):
                ot = units[o]["unitType"]
                return (at.get("attackBonus") or {}).get(ot["unitClass"], 0) - (ot.get("defenseBonus") or {}).get(at["unitClass"], 0)

            ch = s["attackedUnitId"]
            lbl = "player" if a["teamFlag"] == 1 else "enemy"
            n[lbl] += 1
            crit[lbl]["nearest"] += hexdist(start, cur[ch]) == min(hexdist(start, cur[o]) for o in cands)
            crit[lbl]["max modifier among reachable"] += mod(ch) == max(mod(o) for o in rc_)
            best = sorted(rc_, key=lambda o: (-mod(o), hexdist(start, cur[o])))[0]
            crit[lbl]["max modifier, tie->nearest (exact)"] += ch == best
    for lbl in n:
        print(f"   {lbl}: {n[lbl]} attacks")
        for k, v in crit[lbl].items():
            print(f"      {k:40} {v / n[lbl]:6.1%}")

    hr("6. DEBUFF / ABILITY APPLICATION")
    applied = total = mod_changed = 0
    for b in B:
        for s, units, cur, start, end, path, dead, amt in replay(b):
            if "attackedUnitId" not in s:
                continue
            total += 1
            applied += bool(s.get("targetNewBuffs"))
            at = units[s["unitId"]]["unitType"]
            tt = units[s["attackedUnitId"]]["unitType"]
            pred = (at.get("attackBonus") or {}).get(tt["unitClass"], 0) - (tt.get("defenseBonus") or {}).get(at["unitClass"], 0)
            mod_changed += s.get("attackModifier", 0) != pred
    print(f"   attacks that applied a debuff: {applied}/{total} ({applied/total:.0%})")
    print(f"   attacks whose attackModifier was altered by active buffs: {mod_changed}/{total} ({mod_changed/total:.0%})")
    print("   rule: modifier = (1 + atk - def) * (1 + attackerAtkBuff) * (1 - targetDefBuff) - 1   [verified on samples]")

    hr("7. SIMULATOR FIDELITY  (simulate_battle with ACTUAL lineup vs ACTUAL result)")
    rows = []
    for b in B:
        st = b["state"]
        p = sorted([u for u in st["unitsOrder"] if u["teamFlag"] == 1], key=lambda u: bd.Y_TO_SLOT[u["startpos"].get("y", 0)])
        e = sorted([u for u in st["unitsOrder"] if u["teamFlag"] == 2], key=lambda u: bd.Y_TO_SLOT[u["startpos"].get("y", 0)])
        p_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in p) / 5)
        e_sq = int(sum(u["startAmountOfUnits"] * u["unitType"]["unitWeight"] for u in e) / 5)
        buffs = {"hp": p[0]["startHitpoints"] / p[0]["unitType"]["hitpoints"] - 1, "atk": CITY_ATK}
        sim = bd.simulate_battle([u["unitType"]["unitTypeId"] for u in p], [u["unitType"]["unitTypeId"] for u in e], p_sq, e_sq, buffs, None)
        act = sum((u["startAmountOfUnits"] - (u.get("amountOfUnits") or 0)) * u["unitType"]["unitWeight"] for u in p) / (p_sq * 5) * 100
        rows.append((st["winnerBit"] == 1, act, sim["won"], sim["loss_pct"]))
    N = len(rows)
    err = [abs(r[1] - r[3]) for r in rows]
    agree = sum(r[0] == r[2] for r in rows)
    lost = [r for r in rows if not r[0]]
    mx, my = sum(r[1] for r in rows) / N, sum(r[3] for r in rows) / N
    cov = sum((r[1] - mx) * (r[3] - my) for r in rows)
    vx = sum((r[1] - mx) ** 2 for r in rows)
    vy = sum((r[3] - my) ** 2 for r in rows)
    print(f"   battles {N} | outcome agreement {agree}/{N} | real defeats predicted as defeat: {sum(not r[2] for r in lost)}/{len(lost)}")
    print(f"   loss% MAE {sum(err)/N:.1f} pts | bias(sim-real) {my - mx:+.1f} pts | Pearson r {cov / math.sqrt(vx * vy):.3f}")
    print(f"   |err|<=5: {sum(x <= 5 for x in err)}  <=10: {sum(x <= 10 for x in err)}  >20: {sum(x > 20 for x in err)}")
    print("   TARGETS (roadmap): MAE <= 6 pts, Pearson >= 0.90, all real defeats flagged as risky")


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(SCRIPT_DIR, "..", "..", "Batte AI Data", "*.json")))
    if not files:
        print(__doc__)
        sys.exit(1)
    main(files)
