# Biên Bản Bàn Giao Phase P0 — Chuẩn Hóa Đo Lường, Step-Replay Test & Tập Holdout

- **Subagent thực thi:** Gemini 3.8 Flash
- **Thời gian hoàn thành:** 2026-11-07 12:58 (UTC+7)
- **Trạng thái:** READY FOR REVIEW

---

## 1. Tóm tắt các thay đổi đã thực hiện

### 1. Tạo mới `tools/test_step_replay.py`
- **Mục đích:** Xây dựng công cụ kiểm định vi mô (micro-verification) 3 định luật vật lý cơ bản từ dữ liệu gốc `InstantBattleResultVO.state.stepHistory`.
- **Dữ liệu nạp:** Tự động nạp đủ 4 file dump chuẩn:
  1. `D:\ElvenarAuto\Batte AI Data\(tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json` (31 trận)
  2. `D:\ElvenarAuto\Batte AI Data\elvenar_debug_dump_live_2026-11-06T08-08-29-735Z.json` (4 trận)
  3. `D:\ElvenarAuto\elvenar_debug_dump_live_2026-11-05T17-50-42-275Z.json` (2 trận)
  4. `D:\ElvenarAuto\elvenar_debug_dump_live_2026-11-05T18-54-06-095Z.json` (3 trận)
  Tổng cộng: 40 trận = 953 đòn tấn công, 178 đòn phản kích.
- **Triển khai 3 định luật:**
  - **Định luật `attackModifier`**: Tra cứu thời lượng kỹ năng từ `ALL_UNITS_DB.ab[]`, theo dõi tick-down debuff ở đầu mỗi Round (`cur_order_idx <= prev_order_idx`), công thức `eff_atk * eff_def - 1`. Đạt độ khớp sai số $\le 1$: **950/953 (99.69%)**.
  - **Định luật `killedUnits` (HP Pool + `topHp`)**: Tính trên tổng pool máu `(amt - 1) * thp + top_hp` và `math.ceil(rem / thp)`. Đạt độ khớp sai số $\pm 1$: **936/953 (98.22%)** (khớp chính xác tuyệt đối: **904/953 = 94.86%**).
  - **Định luật `retaliationDamage` (Phản đòn 50%)**: Đo tỷ lệ `retaliationDamage / full_counter_dmg` trên 178 sự kiện phản kích sau khi đã áp dụng debuff của đòn đánh vừa trúng. Trung vị (p50) đạt **0.471** ($\approx 0.47 - 0.50$).

### 2. Cập nhật `tools/audit_engine_fidelity.py`
- Thêm tham số CLI `--split [all|train|holdout]` và cờ `--holdout`.
- Quy chuẩn danh sách 4 file dump mặc định `DEFAULT_DUMP_FILES` thay vì chỉ glob 1 thư mục.
- Cố định phân chia deterministic: **30 trận đầu (`idx 0..29`) là `TRAIN`**, **10 trận cuối (`idx 30..39`) là `HOLDOUT`**.
- Tại Mục `7. SIMULATOR FIDELITY`: Thêm các hàm `print_kpi_block` và `calc_kpi_dict`, in đầy đủ chi tiết và bảng Markdown tổng hợp so sánh cả 3 tập: `ALL (40)`, `TRAIN (30)`, `HOLDOUT (10)`.

### 3. Cập nhật `tools/benchmark_dump.py`
- Sửa lỗi phương pháp luận: Khởi tạo mảng `actual_sim_results = []` và chạy `simulate_battle` cho cả đội hình thực tế của người chơi (`actual_p_keys = [x["id"] for x in p_units]`) song song với đội hình đề xuất Advisor (`r661`).
- Sửa bảng in từng trận: Hiển thị đủ 4 cột so sánh:
  `Actual Real` | `Actual Sim` | `Advisor Sim` | `Fair Outcome`
- Trong `OVERALL PERFORMANCE SUMMARY`: Bổ sung bảng đối chiếu 3 cột (`Actual Played (Real)` | `Actual Lineup (Sim)` | `Advisor v6.6.1 (Sim)`), báo cáo rõ ràng:
  - `Simulator Fidelity MAE (|Actual Sim - Actual Real|)`
  - `Fair Sim-vs-Sim Delta (Actual Sim Avg - Advisor Sim Avg)`
  - Phân bổ dải thương vong (Casualty Distribution Brackets) cho cả 3 cột.

---

## 2. Kết quả chạy Bộ Kiểm Định (Verification Output)

### 2.1. Kết quả `python tools/test_step_replay.py`
```text
=====================================================================================
ELVENAR RADAR — STEP-REPLAY COMBAT LAWS VERIFICATION
=====================================================================================
[+] Loaded Dump Files (4):
    - (tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json
    - elvenar_debug_dump_live_2026-11-06T08-08-29-735Z.json
    - elvenar_debug_dump_live_2026-11-05T17-50-42-275Z.json
    - elvenar_debug_dump_live_2026-11-05T18-54-06-095Z.json
[+] (tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json: 31 battles cumulative
[+] elvenar_debug_dump_live_2026-11-06T08-08-29-735Z.json: 35 battles cumulative
[+] elvenar_debug_dump_live_2026-11-05T17-50-42-275Z.json: 37 battles cumulative
[+] elvenar_debug_dump_live_2026-11-05T18-54-06-095Z.json: 40 battles cumulative
[+] Total Battles Ingested: 40

=====================================================================================
1. LAW 1: ATTACK MODIFIER (eff_atk * eff_def - 1) & DEBUFF ENGINE
=====================================================================================
   Total Attacks Evaluated : 953
   Exact Match (diff == 0) : 949/953 (99.58%)
   Tolerance ±1 Match      : 950/953 (99.69%)
   Expected Benchmark      : 950/953 (99.69%)

=====================================================================================
2. LAW 2: KILLED UNITS (HP POOL + topHp MODEL)
=====================================================================================
   Total Attacks Evaluated : 953
   Exact Match (diff == 0) : 904/953 (94.86%)
   Tolerance ±1 Match      : 936/953 (98.22%)
   Acceptance Threshold    : >= 94.00%

=====================================================================================
3. LAW 3: RETALIATION DAMAGE (50% COUNTER-ATTACK)
=====================================================================================
   Total Retaliation Events: 178
   Ratio (retaliationDamage / full_counter_dmg):
     - p25 (25th percentile): 0.439
     - p50 (Median)         : 0.471   [Expected: ~0.47 - 0.50]
     - p75 (75th percentile): 0.535

=====================================================================================
ACCEPTANCE GATE EVALUATION (PHASE P0)
=====================================================================================
   [Gate 1] Attack Modifier (>= 99.50%): PASS (99.69%)
   [Gate 2] Killed Units ±1 (>= 94.00%): PASS (98.22%)
   [Gate 3] Retaliation Median in [0.45, 0.52]: PASS (0.471)

>>> ALL PHASE P0 ACCEPTANCE GATES PASSED! <<<
```

### 2.2. Kết quả `python tools/audit_engine_fidelity.py --split all`

| Tập dữ liệu | Battles | Outcome Agreement | Real Defeats Flagged | Loss% MAE | Bias (Sim - Real) | Pearson r |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Trước Phase P0** | 40 | 38/40 (95.0%) | 0/2 (0.0%) | 12.8 pts | -4.4 pts | 0.706 |
| **Sau Phase P0 (ALL 40)** | 40 | 38/40 (95.0%) | 0/2 (0.0%) | 12.8 pts | -4.4 pts | 0.706 |
| **Sau Phase P0 (TRAIN 30)** | 30 | 29/30 (96.7%) | 0/1 (0.0%) | 10.7 pts | -0.8 pts | 0.800 |
| **Sau Phase P0 (HOLDOUT 10)** | 10 | 9/10 (90.0%) | 0/1 (0.0%) | 19.0 pts | -15.3 pts | 0.559 |

### 2.3. Kết quả `python tools/benchmark_dump.py` (Mẫu trên 31 trận Tourney 6★)
```text
OVERALL PERFORMANCE SUMMARY: ACTUAL PLAYED vs ACTUAL SIMULATED vs ADVISOR v6.6.1
==========================================================================================
Metric                     | Actual Played (Real)   | Actual Lineup (Sim)    | Advisor v6.6.1 (Sim)  
------------------------------------------------------------------------------------------
Win Rate                   | 30/31 ( 96.8%)          | 31/31 (100.0%)          | 31/31 (100.0%)
Average Casualties         |  32.0%                 |  30.8%                 |  28.4%
------------------------------------------------------------------------------------------
[*] Simulator Fidelity MAE (|Actual Sim - Actual Real|): 10.75 pts
[*] Fair Sim-vs-Sim Delta (Actual Sim Avg - Advisor Sim Avg): +2.43 pts (Advisor Better)
```

### 2.4. Kiểm tra đồng bộ Python vs JS (`index.html`)
- Trong Phase P0, chưa can thiệp vào logic tính toán bên trong `simulate_battle` (Python) và `simulateBattle` (JS) (việc này sẽ thực thi trong Phase P1).
- Cơ chế đọc game database `load_game_db_from_index()` từ `index.html` trong `benchmark_dump.py` tiếp tục hoạt động đồng bộ 100%.

---

## 3. Các vấn đề phát sinh / Lưu ý cho Lead Agent
1. **Dữ liệu 4 dump chuẩn**:
   - `Batte AI Data\(tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json`: 31 trận (trận 0..29 thuộc `TRAIN`, trận 30 thuộc `HOLDOUT`).
   - 3 file dump còn lại gồm 4 + 2 + 3 = 9 trận thuộc `HOLDOUT`.
   - Tổng cộng 40 trận cố định, đảm bảo mọi đo lường từ Phase P1 đến P5 hoàn toàn độc lập trên tập holdout.
2. **Quy tắc Git**:
   - Tuân thủ nghiêm ngặt chỉ đạo của Lead Agent, Subagent **KHÔNG** thực hiện lệnh `git commit` hay `git push`. Toàn bộ file đã sẵn sàng để Lead Agent review và phê duyệt.
