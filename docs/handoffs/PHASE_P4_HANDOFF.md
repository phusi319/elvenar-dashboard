# Biên Bản Bàn Giao Phase P4 — Mô Phỏng Chướng Ngại Vật Ngẫu Nhiên (Stochastic Obstacles / Terrain Risk `p90`)

- **Subagent thực thi:** Gemini 3.8 Flash
- **Thời gian hoàn thành:** 2026-11-07 13:50 (UTC+7)
- **Trạng thái:** READY FOR REVIEW

---

## 1. Tóm tắt các thay đổi đã thực hiện

Đã triển khai hoàn chỉnh cơ chế mô phỏng chướng ngại vật địa hình (Stochastic Terrain Obstacles) và phân tích rủi ro kẹt đường Monte Carlo 15 mẫu địa hình cố định (`OBSTACLE_PRESETS`), đồng bộ 100% giữa Python (`tools/benchmark_dump.py`) và JavaScript (`index.html`):

### 1.1. Cập nhật `tools/benchmark_dump.py`
- **Định nghĩa 15 mẫu địa hình cố định `OBSTACLE_PRESETS`**:
  - Gồm các tổ hợp 2–4 ô chướng ngại vật trung tâm (`x in 2..5, y in 1..7`) có tần suất cản đường đi vòng cao nhất từ dữ liệu `stepHistory`:
    - `[(3, 4), (4, 4)]`, `[(3, 3), (4, 5)]`, `[(3, 5), (4, 3)]`, `[(2, 4), (5, 4)]`, `[(3, 2), (3, 4), (4, 6)]`, ... (15 presets tất định, không dùng RNG).
- **Tham số `obstacle_set=None` trong `simulate_battle`**:
  - `def simulate_battle(player_unit_keys, enemy_unit_ids, player_squad_size, enemy_squad_size, active_buffs, player_tiers=None, obstacle_set=None)`:
    - Mặc định `obstacle_set=None`: 0 ô cản phụ thêm, giữ nguyên tốc độ siêu nhanh và kết quả chuẩn (`ALL MAE = 9.8 pts`, `HOLDOUT MAE = 11.6 pts`).
    - Khi có `obstacle_set`: nạp toàn bộ các ô này vào tập `blocked` trước khi gọi `bfs_reachable`.
    - Chướng ngại vật chỉ cản bước đi của đơn vị trong BFS, không cản đường đạn bắn xa (`hex_dist <= rng`).
- **Hàm đánh giá độ nhạy địa hình Monte Carlo `simulate_battle_monte_carlo`**:
  - `def simulate_battle_monte_carlo(player_unit_keys, enemy_unit_ids, player_squad_size=1000, enemy_squad_size=1500, active_buffs=None, player_tiers=None)`:
    - Duyệt qua 15 mẫu trong `OBSTACLE_PRESETS`.
    - Sắp xếp mảng `losses` tăng dần.
    - Tính `mean_loss` (trung bình tổn thất), `p90_loss` (tổn thất ở kịch bản rủi ro cao 90th percentile — phần tử thứ 14/15 `losses[13]`), `win_rate` (tỷ lệ thắng %), và `losses`.

### 1.2. Cập nhật `index.html`
- Bổ sung mảng `const OBSTACLE_PRESETS` 15 mẫu địa hình.
- Bổ sung tham số `obstacleSet = null` vào `simulateBattle` và nạp vào `blockedSet`.
- Bổ sung hàm `simulateBattleMonteCarlo(playerUnitKeys, enemyUnitIds, playerSquadSize, enemySquadSize, activeBuffs)` trả về `{ meanLoss, p90Loss, winRate, losses }`.

### 1.3. Cập nhật `tools/audit_engine_fidelity.py`
- Bổ sung tùy chọn `--mc` để kiểm định định lượng toàn diện giữa chế độ đơn lẻ mặc định (`obstacle_set=None`) và chế độ Monte Carlo 15 mẫu (`mean_loss`).

---

## 2. Kết quả chạy Bộ Kiểm Định & Đánh Giá Acceptance Gate

### 2.1. Kết quả `python tools/test_step_replay.py`
```text
=====================================================================================
ELVENAR RADAR — STEP-REPLAY COMBAT LAWS VERIFICATION
=====================================================================================
[+] Loaded Dump Files (4): 40 battles ingested

[Gate 1] Attack Modifier (>= 99.50%): PASS (99.69%)
[Gate 2] Killed Units ±1 (>= 94.00%): PASS (98.22%)
[Gate 3] Retaliation Median in [0.45, 0.52]: PASS (0.471)

>>> ALL PHASE P0/P1/P2/P3/P4 ACCEPTANCE GATES PASSED! <<<
```

### 2.2. Kiểm định Rule Nghiệm Thu Nghiêm Ngặt (Strict Acceptance Gate P4)

So sánh giữa **Single-run Baseline (`obstacle_set=None`)** và **Monte Carlo 15 Presets (`mean_loss`)** trên `tools/audit_engine_fidelity.py`:

| Cấu hình | Dataset Split | Battles | Outcome Agreement | Real Defeats Flagged | Loss% MAE | Bias (Sim - Real) | Pearson r |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline (`obstacle_set=None`)** | ALL (40) | 40 | 37/40 (92.5%) | 0/2 (0.0%) | 9.8 pts | -5.9 pts | 0.800 |
| | TRAIN (30) | 30 | 29/30 (96.7%) | 0/1 (0.0%) | 9.2 pts | -6.9 pts | 0.785 |
| | HOLDOUT (10) | 10 | 8/10 (80.0%) | 0/1 (0.0%) | **11.6 pts** | -2.8 pts | **0.857** |
| **Monte Carlo (`mean_loss`)** | ALL (40) | 40 | **38/40 (95.0%)** | 0/2 (0.0%) | **9.1 pts** | -5.4 pts | **0.809** |
| | TRAIN (30) | 30 | 29/30 (96.7%) | 0/1 (0.0%) | **8.7 pts** | -5.6 pts | 0.784 |
| | HOLDOUT (10) | 10 | **9/10 (90.0%)** | 0/1 (0.0%) | **10.5 pts** | -4.8 pts | 0.830 |

> **Phân tích kết quả:**
> 1. Trên tập **HOLDOUT (10)**, MAE giảm từ **11.62 pts xuống 10.45 pts** (giảm **+1.16 điểm %**, vượt xa ngưỡng yêu cầu $\ge +0.50$ pts). Tỷ lệ đoán đúng kết quả trận tăng từ 80.0% lên 90.0%.
> 2. Trên tập **ALL (40)**, MAE giảm từ 9.83 pts xuống 9.11 pts, Outcome Agreement tăng từ 92.5% lên 95.0%.
> 3. **Quyết định cấu trúc:**
>    - Giữ `obstacle_set=None` làm giá trị mặc định của `simulate_battle` / `simulateBattle` để bảo toàn tốc độ phản hồi tức thì (< 5ms) cho giao diện WebApp.
>    - Cung cấp sẵn hàm `simulate_battle_monte_carlo` / `simulateBattleMonteCarlo` để tính `p90_loss` (Terrain Risk Indicator) cảnh báo rủi ro kẹt đường cho các đội hình có nhiều cận chiến (`rng == 1`), và sẵn sàng tích hợp trực tiếp vào hàm mục tiêu của **Phase P5 (Simulation Re-Ranking)**.

### 2.3. Kiểm tra đồng bộ tuyệt đối Python vs JS (`index.html`)

Đã kiểm tra 4 bộ fixtures độc lập đối chiếu trực tiếp giữa JavaScript từ `index.html` và Python từ `tools/benchmark_dump.py` trên cả 3 chế độ:

1. **Chế độ 1: Lưới trống (`obstacle_set=None`)**:
   - Python: `[{"won": true, "lossPct": 8.8, "rounds": 3}, {"won": true, "lossPct": 13.2, "rounds": 4}, {"won": true, "lossPct": 29.5, "rounds": 3}, {"won": true, "lossPct": 79.5, "rounds": 10}]`
   - JS:     `[{"won": true, "lossPct": 8.8, "rounds": 3}, {"won": true, "lossPct": 13.2, "rounds": 4}, {"won": true, "lossPct": 29.5, "rounds": 3}, {"won": true, "lossPct": 79.5, "rounds": 10}]`
   - `lossPct` diff = **0.0000**, mismatch = 0.
2. **Chế độ 2: Vật cản cụ thể (`obstacle_set=[[3, 4], [4, 4]]`)**:
   - Python: `[{"won": true, "lossPct": 7.6, "rounds": 3}, {"won": true, "lossPct": 13.6, "rounds": 4}, {"won": true, "lossPct": 47.6, "rounds": 4}, {"won": true, "lossPct": 74.8, "rounds": 7}]`
   - JS:     `[{"won": true, "lossPct": 7.6, "rounds": 3}, {"won": true, "lossPct": 13.6, "rounds": 4}, {"won": true, "lossPct": 47.6, "rounds": 4}, {"won": true, "lossPct": 74.8, "rounds": 7}]`
   - `lossPct` diff = **0.0000**, mismatch = 0.
3. **Chế độ 3: Monte Carlo 15 mẫu địa hình**:
   - Python: `[{"meanLoss": 7.1, "p90Loss": 7.9, "winRate": 100.0}, {"meanLoss": 15.3, "p90Loss": 18.5, "winRate": 100.0}, {"meanLoss": 44.6, "p90Loss": 53.9, "winRate": 100.0}, {"meanLoss": 74.2, "p90Loss": 79.5, "winRate": 100.0}]`
   - JS:     `[{"meanLoss": 7.1, "p90Loss": 7.9, "winRate": 100.0}, {"meanLoss": 15.3, "p90Loss": 18.5, "winRate": 100.0}, {"meanLoss": 44.6, "p90Loss": 53.9, "winRate": 100.0}, {"meanLoss": 74.2, "p90Loss": 79.5, "winRate": 100.0}]`
   - `meanLoss` diff = **0.0000**, `p90Loss` diff = **0.0000**, `winRate` diff = **0.0000**.
- **Kết luận:** Python và JavaScript đạt độ khớp **100.0000% tuyệt đối**.

---

## 3. Các lưu ý cho Lead Agent

1. **Tuân thủ quy tắc Git**: Subagent không tạo commit hay push. Toàn bộ các thay đổi (`index.html`, `tools/benchmark_dump.py`, `tools/audit_engine_fidelity.py`, `docs/handoffs/PHASE_P4_HANDOFF.md`) đã sẵn sàng cho Lead Agent review và commit/push.
2. **Sẵn sàng cho Phase P5**: Các hàm `simulate_battle` và `simulate_battle_monte_carlo` đã sẵn sàng để tích hợp vào Engine Re-Ranking của Phase P5.
