# 📋 Playbook Giao Việc & Đặc Tả Triển Khai Chi Tiết Cho Subagent (Gemini 3.8 Flash)

> **Tài liệu gốc:** [`docs/BATTLE_ENGINE_AUDIT_ROADMAP.md`](./BATTLE_ENGINE_AUDIT_ROADMAP.md)
> **Mục đích:** Chia nhỏ lộ trình nâng cấp Battle Simulator & Recommendation Engine thành **6 gói công việc (Work Packages P0 → P5)** có đặc tả toán học, tên hàm, vị trí dòng code, lệnh kiểm thử và mẫu biên bản bàn giao chuẩn hóa.
> **Cơ chế vận hành:**
> 1. **Lead Agent (Reviewer / Architect)** gọi subagent `Model: "flash"` (Gemini 3.8 Flash) thực thi từng Phase độc lập.
> 2. **Subagent Flash** chỉ thực hiện đúng phạm vi của Phase được giao, chạy bộ kiểm định (`audit_engine_fidelity.py`, `test_step_replay.py`, `benchmark_dump.py`) và ghi biên bản bàn giao vào `docs/handoffs/PHASE_P<X>_HANDOFF.md`.
> 3. **Lead Agent** kiểm tra diff, chạy lại bài test độc lập, nghiệm thu KPI trước khi chuyển sang Phase kế tiếp và thực hiện Git Push theo quy tắc dự án.

---

## 🛡️ Quy Tắc Bất Di Bất Dịch Dành Cho Subagent Flash

1. **Đồng bộ tuyệt đối Python & JS**:
   - Mọi thay đổi trong logic simulator hoặc scoring (từ Phase P1 trở đi) **BẮT BUỘC** phải cập nhật song song ở cả 2 nơi:
     - `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py`
     - `D:\ElvenarAuto\elvenar-dashboard\index.html`
2. **Bảo toàn giao diện & dữ liệu**:
   - Không xóa hoặc làm hỏng các hàm UI hiện có trong `index.html` (`renderAdvisorUI`, `openEnemyPickerModal`, `loadPresetEncounter`, v.v.).
   - Không sửa đổi `elvenar-radar.user.js` trừ khi Phase có yêu cầu rõ ràng.
3. **Không tự ý Commit/Push khi chưa qua cổng Review**:
   - Subagent chỉ ghi file code + biên bản bàn giao `docs/handoffs/PHASE_P<X>_HANDOFF.md` và trả kết quả về cho Lead Agent. Lead Agent sẽ review và thực thi lệnh Git Commit & Push + Purge CDN.
4. **Cổng KPI (Quality Gate)**:
   - Không một Phase nào được phép làm giảm chỉ số trên tập kiểm định (`tools/audit_engine_fidelity.py`).

---

## 📦 PHASE P0 — Chuẩn Hóa Đo Lường, Step-Replay Test & Tập Holdout

### 1. Mục tiêu
Xây dựng bộ khung kiểm thử chuẩn xác 100% dựa trên `InstantBattleResultVO.state.stepHistory` và sửa lỗi phương pháp luận trong `benchmark_dump.py` (so sánh công bằng `Sim(Actual Lineup)` vs `Sim(Advisor Lineup)`).

### 2. File tạo mới / chỉnh sửa
- **Tạo mới:** `D:\ElvenarAuto\elvenar-dashboard\tools\test_step_replay.py`
- **Chỉnh sửa:** `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py`
- **Chỉnh sửa:** `D:\ElvenarAuto\elvenar-dashboard\tools\audit_engine_fidelity.py` (thêm cờ `--holdout`)
- **Bàn giao:** `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P0_HANDOFF.md`

### 3. Đặc tả kỹ thuật chi tiết (Exact Spec)

#### A. `tools/test_step_replay.py` (Kiểm thử từng bước đánh theo `stepHistory`)
Viết script độc lập nạp toàn bộ 40 trận (953 đòn tấn công, 178 đòn phản kích) từ 4 file dump và kiểm tra 3 định luật vật lý của server:
1. **Định luật `attackModifier` (mục tiêu khớp $\ge 99.5\%$, thực tế đạt `950/953 = 99.69%`)**:
   - Tra cứu thời lượng gốc `d` của mỗi kỹ năng từ `ALL_UNITS_DB[unit].ab[]` theo tên `bv["name"].strip()`.
   - Mỗi đơn vị duy trì 2 slot debuff: `attack_negative` (`val`, `dur`) và `defense_negative` (`val`, `dur`).
   - Đầu mỗi Round mới (khi `order.index(uid) <= prev_order_index`), giảm `dur -= 1` cho toàn bộ debuff đang hoạt động trên mọi đơn vị; xóa debuff nếu `dur <= 0`.
   - Công thức tính `pred_mod`:
     ```python
     eff_atk = (1.0 + atk_b / 100.0) * (1.0 + a_debuff / 100.0)
     eff_def = (1.0 - def_b / 100.0) * (1.0 - d_debuff / 100.0)
     pred_mod = round((eff_atk * eff_def - 1.0) * 100)
     ```
   - Sau khi tính sát thương, nạp `s.get("targetNewBuffs")` vào mục tiêu `tid` với `dur = ab_dur.get(bname, 1)`.
2. **Định luật `killedUnits` theo HP Pool + `topHp` (mục tiêu khớp $\pm 1$ lính $\ge 94\%$)**:
   - Mỗi đơn vị lưu `amt` (số lính hiện tại) và `top_hp` (máu còn lại của con lính đứng đầu hàng, khởi tạo bằng `startHitpoints`).
   - Khi nhận `dealtDamage`:
     ```python
     thp = t_unit["startHitpoints"] if t_unit["teamFlag"] == 1 else t_unit["unitType"]["hitpoints"]
     pool = (amt - 1) * thp + top_hp
     rem = max(0, pool - dealt_damage)
     pred_alive = math.ceil(rem / thp) if rem > 0 else 0
     pred_killed = amt - pred_alive
     ```
   - Cập nhật `top_hp = s.get("attackedUnitHitpoints", top_hp)` và `amt -= s.get("killedUnits", 0)`.
3. **Định luật `retaliationDamage` (Phản đòn = 50% sát thương cơ bản sau debuff)**:
   - Xác minh tỷ lệ `retaliationDamage / expected_full_counter_damage` có trung vị $\approx 0.47 - 0.50$.

#### B. Sửa bảng đối chiếu trong `tools/benchmark_dump.py`
Trong `run_benchmark(dump_file)`:
- Khi lặp qua từng trận, chạy `simulate_battle` cho **cả 2 đội hình**:
  1. `actual_sim = simulate_battle(actual_player_keys, wave, p_sq, e_sq, active_buffs, player_tiers)`
  2. `advisor_sim = simulate_battle(r661, wave, p_sq, e_sq, active_buffs, player_tiers)`
- Hiển thị bảng 3 cột rõ ràng:
  - `Actual Real Loss` (kết quả thật từ server)
  - `Actual Sim Loss` (simulator chạy trên đội hình người chơi đã chọn)
  - `Advisor Sim Loss` (simulator chạy trên đội hình Advisor đề xuất)
- Trong phần `OVERALL PERFORMANCE SUMMARY`:
  - Báo cáo cả **Sim Fidelity Error (MAE giữa Actual Real và Actual Sim)** lẫn **Fair Sim-vs-Sim Delta (`Actual Sim Loss - Advisor Sim Loss`)**.

#### C. Tập Train / Holdout cố định trong `tools/audit_engine_fidelity.py`
- Thêm tham số CLI `--split [all|train|holdout]`.
- Quy ước cố định (deterministic): Trong 40 trận gộp theo thứ tự chuẩn, **30 trận đầu (`idx 0..29`) là `train`**, **10 trận cuối (`idx 30..39`, gồm 1 trận cuối của dump 6★ + 9 trận của 3 dump ngày 05–06/11) là `holdout`**.
- In rõ bảng KPI cho cả `ALL (40)`, `TRAIN (30)` và `HOLDOUT (10)`.

### 4. Tiêu chí nghiệm thu (Acceptance Gate)
- `python tools/test_step_replay.py` chạy thành công, in ra `attackModifier match: 950/953 (99.69%)` và `killedUnits (±1) match: >= 94.0%`.
- `python tools/audit_engine_fidelity.py --split all` in đủ 3 khối KPI (`ALL`, `TRAIN`, `HOLDOUT`).
- `python tools/benchmark_dump.py` in bảng 3 cột `Real | Sim(Actual) | Sim(Advisor)`.

---

## 📦 PHASE P1 — Chuẩn Hóa Toán Học Chiến Đấu (Combat Math, HP Pool & Retaliation 50%)

### 1. Mục tiêu
Khắc phục 4 sai lệch toán học cơ bản trong `simulate_battle` (Python) và `simulateBattle` (JS):
1. Sát thương phản kích (Retaliation) đang tính 100% thay vì **50% (`0.50x`)**.
2. Điều kiện phản kích đang khóa cứng `attacker.rng == 1` thay vì kiểm tra tầm bắn của mục tiêu (`bestTarget.rng >= attacker.rng` khi chưa có lưới hex, hoặc `hexDist <= bestTarget.rng`).
3. Tính số lính chết bằng **Tổng HP Pool (`totalHpPool`)** thay vì làm tròn xuống `int(dealt_dmg / hp_per_unit)` mỗi đòn (vốn làm mất sạch sát thương lẻ dưới 1 con lính!).
4. Bổ sung hệ số kỳ vọng sát thương `E[rand] = 1.07` (do biến thiên ngẫu nhiên thực tế trong game có trung vị $+6.8\% \sim +7.9\%$).

### 2. File chỉnh sửa
- `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py` (`simulate_battle`)
- `D:\ElvenarAuto\elvenar-dashboard\index.html` (`simulateBattle`)
- **Bàn giao:** `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P1_HANDOFF.md`

### 3. Đặc tả kỹ thuật chi tiết (Exact Spec)

#### A. Khởi tạo HP Pool cho mỗi đạo quân (`p_units` và `e_units`)
Thêm thuộc tính `hp_pool` (Python) / `hpPool` (JS) khi khởi tạo mỗi unit:
```python
hp_per_unit = u["hp"] * hp_mult  # (hoặc u["hp"] cho địch)
u_obj["hp_pool"] = count * hp_per_unit
```

#### B. Tính sát thương & trừ HP Pool khi tấn công
```python
DMG_EXPECTED_MULT = 1.07  # Trung vị thực nghiệm từ 953 đòn đánh trong stepHistory
dealt_dmg = attacker["count"] * attacker["dmg_per_unit"] * (1.0 + atk_b) * (1.0 - def_b) * DMG_EXPECTED_MULT
best_target["hp_pool"] = max(0.0, best_target["hp_pool"] - dealt_dmg)
best_target["count"] = math.ceil(best_target["hp_pool"] / best_target["hp_per_unit"]) if best_target["hp_pool"] > 0 else 0
```

#### C. Điều kiện & Sát thương Phản Kích (Retaliation 50%)
Trong `stepHistory`, mục tiêu phản đòn khi mục tiêu còn sống (`best_target["count"] > 0`), còn lượt phản đòn (`best_target["ret_left"] > 0`), và kẻ tấn công đứng trong tầm đánh của mục tiêu (trước Phase P3 khi chưa có lưới hex, điều kiện tương đương là `attacker["rng"] <= best_target["rng"]`):
```python
RETALIATION_MULT = 0.50  # Chứng minh từ 178 mẫu retaliationDamage trong stepHistory
if attacker["rng"] <= best_target["rng"] and best_target["count"] > 0 and best_target["ret_left"] > 0:
    ret_atk_b = (best_target["u"].get("atk", {}).get(attacker["cls"], 0)) / 100.0
    ret_def_b = (attacker["u"].get("def", {}).get(best_target["cls"], 0)) / 100.0
    ret_dmg = best_target["count"] * best_target["dmg_per_unit"] * (1.0 + ret_atk_b) * (1.0 - ret_def_b) * DMG_EXPECTED_MULT * RETALIATION_MULT
    attacker["hp_pool"] = max(0.0, attacker["hp_pool"] - ret_dmg)
    attacker["count"] = math.ceil(attacker["hp_pool"] / attacker["hp_per_unit"]) if attacker["hp_pool"] > 0 else 0
    best_target["ret_left"] -= 1
```
*(Áp dụng y hệt sang hàm `simulateBattle` trong `index.html`).*

### 4. Tiêu chí nghiệm thu (Acceptance Gate)
- Kết quả `simulate_battle` (Python) và `simulateBattle` (JS) khớp nhau 100% trên cùng đầu vào.
- Chạy `python tools/audit_engine_fidelity.py --split all`: Ghi nhận chỉ số chuyển tiếp (Lưu ý: trên mô hình 1D cũ trước khi lắp lưới Hex 8×9 ở Phase P3, MAE toàn cục sẽ ở mức chuyển tiếp `~13.5 pts` do heuristic 1D cũ `reach < 6` chưa bị gỡ bỏ; chỉ số này sẽ giảm mạnh xuống **`9.83 pts`** ngay khi lắp lưới Hex ở Phase P3).

---

## 📦 PHASE P2 — Mô Phỏng Debuff Đa Hiệp (Multi-Round Active Debuffs Engine)

### 1. Mục tiêu
Đưa cơ chế **On-Hit Special Abilities (`attack_negative` & `defense_negative`)** vào simulator. Trong dữ liệu thực tế, **85% đòn đánh** kích hoạt debuff và **48% đòn đánh** bị thay đổi sát thương bởi debuff (ví dụ: Senior Orc Strategist giảm 30% công địch, Banshee giảm 50% giáp địch khiến Drone Rider chém $+185\%$ sát thương!).

### 2. File chỉnh sửa
- `D:\ElvenarAuto\elvenar-dashboard\index.html` (`ALL_UNITS_DB`, `simulateBattle`)
- `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py` (`simulate_battle`)
- **Bàn giao:** `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P2_HANDOFF.md`

### 3. Đặc tả kỹ thuật chi tiết (Exact Spec)

#### A. Đồng bộ Ability cho quái Tier 2 & Tier 3 trong `ALL_UNITS_DB` (`index.html`)
Kiểm tra toàn bộ các entry `mob_*_2` và `mob_*_3` trong `ALL_UNITS_DB`: đảm bảo trường `ab` của `mob_*_3` và `mob_*_2` khớp đúng với `UNIT_STATS_DB` và `AbilityVO` trong dump (không bị rỗng `[]` ở các cấp sao có kỹ năng).

#### B. Cấu trúc trạng thái Debuff trên mỗi Unit trong Simulator
Khi khởi tạo mỗi unit trong `p_units` và `e_units`, thêm:
```python
"atk_debuff": {"val": 0.0, "dur": 0},  # val âm, ví dụ -30.0 nghĩa là giảm 30% công
"def_debuff": {"val": 0.0, "dur": 0},  # val âm, ví dụ -50.0 nghĩa là tăng 50% sát thương nhận vào
```

#### C. Tick-down Duration ở đầu mỗi Round (từ Round 2 trở đi)
Ngay đầu vòng lặp `for round_num in range(1, 16):` (khi `round_num > 1`):
```python
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
```

#### D. Công thức hệ số sát thương có Debuff (chứng minh khớp 99.69% `stepHistory`)
Viết hàm phụ `calc_eff_mult(attacker, target)` dùng chung cho cả AI chấm điểm chọn mục tiêu, đòn đánh chính, và đòn phản kích:
```python
def calc_eff_mult(attacker, target):
    atk_b = (attacker["u"].get("atk", {}).get(target["cls"], 0)) / 100.0
    def_b = (target["u"].get("def", {}).get(attacker["cls"], 0)) / 100.0
    a_deb = attacker["atk_debuff"]["val"] / 100.0   # ví dụ -0.30
    d_deb = target["def_debuff"]["val"] / 100.0     # ví dụ -0.50
    return (1.0 + atk_b) * (1.0 + a_deb) * (1.0 - def_b) * (1.0 - d_deb)
```

#### E. Áp dụng Debuff ngay khi đánh trúng (TRƯỚC khi mục tiêu phản kích!)
Sau khi `attacker` gây sát thương lên `best_target`, nếu `best_target["count"] > 0`:
```python
for ab in attacker["u"].get("ab", []):
    ab_type = ab.get("t")
    ab_val = float(ab.get("v", 0))
    ab_dur = int(ab.get("d", 1))
    if ab_type == "attack" and ab_val < 0:
        best_target["atk_debuff"] = {"val": ab_val, "dur": ab_dur}
    elif ab_type == "defense" and ab_val < 0:
        best_target["def_debuff"] = {"val": ab_val, "dur": ab_dur}
```
Ngay sau đó, nếu `best_target` phản kích (`retaliation`), đòn phản kích của `best_target` sử dụng `calc_eff_mult(best_target, attacker)` — tức là **bị giảm sát thương ngay lập tức bởi `atk_debuff` vừa dính** (đúng 100% theo `stepHistory`!).

### 4. Tiêu chí nghiệm thu (Acceptance Gate)
- `python tools/test_step_replay.py` đạt `attackModifier match >= 99.5%`.
- `python tools/audit_engine_fidelity.py --split all`: Ghi nhận bảng KPI chuyển tiếp sau khi bật Debuff Engine (chuẩn bị cho bước nhảy vọt ở Phase P3 khi thay thế hoàn toàn mô hình 1D bằng lưới Hex 8×9).

---

## 📦 PHASE P3 — Lưới Lục Giác 8×9 (`odd-r`), Pathfinding BFS, Ranged Kiting & AI Target Selection

### 1. Mục tiêu
Thay thế mô hình 1 chiều (`dy`) bằng **lưới lục giác 8×9 thực tế của Elvenar**, mô phỏng chính xác vị trí `(x, y)`, thứ tự ưu tiên Slot `5 -> 4 -> 3 -> 2 -> 1` khi hòa Initiative, di chuyển BFS tránh các ô đã có quân đứng, cơ chế **Ranged Kiting (lính tầm xa lùi về tầm bắn tối đa hướng về sân nhà)**, và hàm chọn mục tiêu của AI đã fit từ `stepHistory`.

### 2. File chỉnh sửa
- `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py`
- `D:\ElvenarAuto\elvenar-dashboard\index.html`
- **Bàn giao:** `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P3_HANDOFF.md`

### 3. Đặc tả kỹ thuật chi tiết (Exact Spec)

#### A. Hình học Lưới Lục Giác 8×9 (`odd-r offset`: hàng `y` lẻ dịch sang phải) & Thứ tự Lượt đi
Đã kiểm chứng `2361/2361` bước đi trong `stepHistory` tuân thủ tuyệt đối hệ tọa độ này (`x in 0..7`, `y in 0..8`). Khi các đơn vị trong cùng một phe có cùng `init`, server sắp xếp theo thứ tự `unitId` từ `-5..-1` (tức **Slot 5 $\to$ 4 $\to$ 3 $\to$ 2 $\to$ 1**):
```python
GRID_W, GRID_H = 8, 9
# Vị trí xuất phát theo Slot 1..5 (SLOT_Y = [4, 3, 5, 2, 6]):
# Team 1 (Player): x = 0, y = SLOT_Y[i]
# Team 2 (Enemy) : x = 7, y = SLOT_Y[i]
# Thứ tự sort lượt đi mỗi round:
all_units.sort(key=lambda u: (u["init"], 1 if u["team"] == 1 else 0, u["slot"]), reverse=True)

def to_cube(x, y):
    q = x - (y - (y & 1)) // 2
    r = y
    return (q, r, -q - r)

def hex_dist(a, b):
    ca, cb = to_cube(a[0], a[1]), to_cube(b[0], b[1])
    return max(abs(ca[0] - cb[0]), abs(ca[1] - cb[1]), abs(ca[2] - cb[2]))

def hex_neighbors(x, y):
    deltas = [(-1, 0), (1, 0), (0, -1), (0, 1)] + ([(-1, -1), (-1, 1)] if (y % 2 == 0) else [(1, -1), (1, 1)])
    return [(x + dx, y + dy) for dx, dy in deltas if 0 <= x + dx < GRID_W and 0 <= y + dy < GRID_H]
```

#### B. BFS Tìm Ô Đứng Tấn Công, Ranged Kiting & Di Chuyển (`bfs_reachable`)
Khi đến lượt `attacker` tại `start = (attacker["x"], attacker["y"])`:
1. Tập hợp các ô bị chặn `blocked = {(u["x"], u["y"]) for u in all_alive_units if u["id"] != attacker["id"]}`.
2. Dùng BFS từ `start` với giới hạn số bước `<= attacker["mv"]` (không đi xuyên qua ô trong `blocked`) để tìm toàn bộ tập ô `reach_cells = {cell: steps_from_start}` (luôn bao gồm `start: 0`).
3. Với mỗi kẻ địch còn sống `tgt` tại `tpos = (tgt["x"], tgt["y"])`, tập ô đứng bắn hợp lệ là `valid_cells = [c for c in reach_cells if hex_dist(c, tpos) <= attacker["rng"]]`.
   - Nếu `valid_cells` không rỗng, số bước tối thiểu để chạm tầm bắn `tgt` là `min_steps = min(reach_cells[c] for c in valid_cells)`.
   - Chọn ô đứng bắn tối ưu `best_c`:
     - **Nếu là lính tầm xa (`attacker["rng"] > 1`) — Cơ chế Ranged Kiting**: Lính tầm xa trong Elvenar luôn giữ khoảng cách xa nhất có thể (lùi về biên sân nhà `x=0` với Team 1, `x=7` với Team 2):
       ```python
       home_sign = 1 if attacker["team"] == 1 else -1
       best_c = min(valid_cells, key=lambda c: (-hex_dist(c, tpos), home_sign * c[0], reach_cells[c]))
       ```
     - **Nếu là lính cận chiến (`attacker["rng"] == 1`)**: Chọn ô tốn ít bước nhất và gần trục `y` xuất phát nhất:
       ```python
       best_c = min(valid_cells, key=lambda c: (reach_cells[c], abs(c[1] - start[1])))
       ```

#### C. Luật Chọn Mục Tiêu Của AI (Target Selection Rule)
- **Trường hợp 1: Có ít nhất 1 mục tiêu trong `cand_targets` (đánh tới được ngay trong lượt)**:
  Chấm điểm từng `(tgt, best_c, min_steps)`:
  ```python
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
  ```
  Di chuyển `attacker` tới `best_c` của mục tiêu có `score` cao nhất, thực hiện tấn công, áp dụng debuff (Phase P2), và kiểm tra phản kích theo khoảng cách thực tế trên lưới hex:
  `hex_dist((attacker["x"], attacker["y"]), (best_t["x"], best_t["y"])) <= best_t["rng"]`.
- **Trường hợp 2: Không có mục tiêu nào đánh tới được trong lượt này (`cand_targets` rỗng)**:
  - Chọn kẻ địch gần nhất `want = min(enemies, key=lambda tgt: hex_dist(start, (tgt["x"], tgt["y"])))`.
  - Di chuyển tới ô trong `reach_cells` giúp thu hẹp khoảng cách `hex_dist` tới `want` nhiều nhất:
    `next_pos = min(reach_cells.keys(), key=lambda c: (hex_dist(c, (want["x"], want["y"])), reach_cells[c], abs(c[1] - start[1])))`
  - Cập nhật `attacker["x"], attacker["y"] = next_pos` và kết thúc lượt.

### 4. Tiêu chí nghiệm thu (Acceptance Gate)
- Chạy `python tools/audit_engine_fidelity.py --split all`:
  - **ALL (40) MAE giảm xuống $\le 10.0$ điểm %** (kỳ vọng đạt **`9.83 pts`**, giảm từ `12.8 pts`).
  - **ALL (40) Pearson $r \ge 0.79$** (kỳ vọng đạt **`0.800`**, tăng từ `0.706`).
  - **HOLDOUT (10) MAE giảm xuống $\le 12.0$ điểm %** (kỳ vọng đạt **`11.62 pts`**, giảm từ `19.0 pts`!).
  - **HOLDOUT (10) Pearson $r \ge 0.85$** (kỳ vọng đạt **`0.857`**, tăng từ `0.559`!).

---

## 📦 PHASE P4 — Mô Phỏng Chướng Ngại Vật Ngẫu Nhiên (Stochastic Obstacles — Tùy Chọn)

### 1. Mục tiêu
Bổ sung chế độ đánh giá độ nhạy địa hình (Monte Carlo $K$ mẫu chướng ngại vật dựa trên phân bố các ô hay bị chặn trong `stepHistory`) để đo rủi ro kẹt đường của đội hình thuần cận chiến (Special Risk Indicator: `p90_loss`).

### 2. Đặc tả kỹ thuật chi tiết
1. Trích xuất danh sách 12 tọa độ ô trung tâm (`x in 2..5, y in 1..7`) có tần suất bị đi vòng cao nhất từ mục 3 của `audit_engine_fidelity.py` (ví dụ: `(3,4), (4,3), (4,5), (5,4), (2,2), (6,2), (6,6), (1,5)`).
2. Thêm tham số `obstacle_set=None` vào `simulate_battle(player_unit_keys, enemy_unit_ids, ..., obstacle_set=None)`.
   - Mặc định `obstacle_set=None` (0 ô cản) để chạy siêu nhanh.
   - Thêm hàm `simulate_battle_monte_carlo(..., k_runs=15)` sinh 15 tổ hợp 2–4 ô cản ngẫu nhiên (không trùng ô xuất phát `x=0` và `x=7`) và trả về `mean_loss`, `p90_loss`, `win_rate`.
3. **Rule nghiệm thu nghiêm ngặt**: Chỉ bật mặc định nếu MAE trên tập `HOLDOUT` giảm thêm $\ge 0.5$ điểm %. Nếu không, giữ làm chỉ số phụ `Terrain Risk (p90)` trên UI cho các đội hình có $\ge 3$ lính cận chiến (`rng == 1`).

---

## 📦 PHASE P5 — Engine Đề Xuất Thế Hệ Mới: Hybrid Heuristic + Simulation Re-Ranking

### 1. Mục tiêu
Chuyển đổi `recommendLineupForWaves` (`index.html`) và `recommend_v661` (`benchmark_dump.py`) từ cơ chế **chọn tham lam từng slot độc lập** sang kiến trúc **2 tầng (Two-Stage Candidate Generation + Full-Team Simulation Re-Ranking)**:
- **Tầng 1 (Fast Heuristic Filter)**: Dùng hàm chấm điểm hiện tại để lấy Top-3 ứng viên tốt nhất cho mỗi slot và sinh ra danh sách ~15–25 đội hình ứng viên sáng giá (gồm: Đội hình Top-1 từng slot, các đội hình đồng nhất 5 lính chủ lực, các biến thể thay thế slot rủi ro cao, và đội hình Fast 1-Tab).
- **Tầng 2 (Simulation Evaluator)**: Chạy trực tiếp `simulateBattle` (đã nâng cấp qua P1–P3) cho toàn bộ 15–25 đội hình ứng viên trên từng Wave (với Spire nhiều wave: truyền số lượng lính còn sống `count` và `hpPool` từ Wave $w$ sang Wave $w+1$!), chọn đội hình tối thiểu hóa hàm mục tiêu:
  $$\text{Objective}(L) = \text{SimulatedLossPct}(L) + 100.0 \times \mathbb{I}(\text{Defeat})$$

### 2. File chỉnh sửa
- `D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py`
- `D:\ElvenarAuto\elvenar-dashboard\index.html`
- **Bàn giao:** `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P5_HANDOFF.md`

### 3. Tiêu chí nghiệm thu (Acceptance Gate)
- Thời gian chạy `recommendLineupForWaves` trên trình duyệt $< 15\text{ ms}$ (tức thời khi người dùng mở tab).
- Trên `benchmark_dump.py` (cả tập `TRAIN` và `HOLDOUT`):
  - `Win Rate` của Advisor đạt **40/40 (100%)**.
  - `Advisor Sim Loss` **thấp hơn hoặc bằng** cả `Actual Sim Loss` lẫn Advisor v6.6.1 cũ trên cả tập `TRAIN` và `HOLDOUT`!

---

## 📝 Mẫu Biên Bản Bàn Giao Cho Subagent (`docs/handoffs/PHASE_P<X>_HANDOFF.md`)

Mỗi khi Subagent Flash hoàn thành 1 Phase, Subagent **BẮT BUỘC** tạo file `D:\ElvenarAuto\elvenar-dashboard\docs\handoffs\PHASE_P<X>_HANDOFF.md` theo đúng cấu trúc sau trước khi kết thúc lượt:

```markdown
# Biên Bản Bàn Giao Phase P<X> — <Tên Phase>

- **Subagent thực thi:** Gemini 3.8 Flash
- **Thời gian hoàn thành:** YYYY-MM-DD HH:MM
- **Trạng thái:** READY FOR REVIEW

## 1. Tóm tắt các thay đổi đã thực hiện
- File 1 (`path/to/file`): Mô tả các hàm đã thêm/sửa và dòng code tương ứng.
- File 2 (`path/to/file`): ...

## 2. Kết quả chạy Bộ Kiểm Định (Verification Output)
### 2.1. Kết quả `python tools/test_step_replay.py`
(Dán nguyên văn output terminal)

### 2.2. Kết quả `python tools/audit_engine_fidelity.py --split all`
| Tập dữ liệu | Outcome Agreement | Real Defeats Flagged | Loss% MAE | Bias (Sim - Real) | Pearson r |
| :--- | :---: | :---: | :---: | :---: | :---: |
| ** Trước Phase P<X> ** | ... | ... | ... | ... | ... |
| ** Sau Phase P<X> (ALL 40) ** | ... | ... | ... | ... | ... |
| ** Sau Phase P<X> (TRAIN 30) ** | ... | ... | ... | ... | ... |
| ** Sau Phase P<X> (HOLDOUT 10) ** | ... | ... | ... | ... | ... |

### 2.3. Kiểm tra đồng bộ Python vs JS (`index.html`)
- Xác nhận các hằng số và nhánh điều kiện trong `simulate_battle` (Python) và `simulateBattle` (JS) khớp nhau 100%.

## 3. Các vấn đề phát sinh / Lưu ý cho Lead Agent
- (Ghi rõ nếu có bất kỳ trường hợp biên nào cần Lead Agent kiểm tra kỹ)
```
