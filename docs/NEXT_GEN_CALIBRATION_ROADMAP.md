# Elvenar Live Radar — Lộ Trình 3 Mảnh Ghép Nâng Cao (Next-Gen Calibration Playbook)

Tài liệu này được lưu cố định trong kho mã nguồn (`docs/NEXT_GEN_CALIBRATION_ROADMAP.md`) để khi có thêm dữ liệu dump từ các kỳ Tournament tiếp theo (9 loại Relic xoay vòng), hệ thống sẽ tiếp tục triển khai phân tích và nâng cấp theo đúng 3 mảnh ghép chiến lược dưới đây.

---

## Mảnh Ghép 1: Tinh Chỉnh Hàm Trọng Số "Bắn Mục Tiêu Trước Mặt vs Đi Bộ 3 Bước" (`stepHistory` Target Calibration)

### Hiện trạng (`Engine v7.1`)
- Hàm chấm điểm chọn mục tiêu trong `simulateBattle` (`index.html`) và `simulate_battle` (`tools/benchmark_dump.py`) hiện tại tính:
  ```javascript
  score = ((em - 1.0) * 180.0) + (kr * 80.0) - (minSteps * 12.0) - (dNow * 6.0) + fb + (e.slot * 1.5);
  ```
- **Điểm cần tinh chỉnh khi có thêm dữ liệu**:
  - Trong trận B03 (Tỉnh 36, Dump `2026-11-07T17-47-17-100Z`), ở Hiệp 0 sau khi *Sneaky Mist Walker* (`-10`) lao lên đứng ở `(4, 3)` (cách Ô 2 `Elite Archer` đúng 4 ô = `minSteps: 0`), 2 đạo `Elite Archer` của người chơi khi đánh Auto đã **chọn bắn luôn *Mist Walker* trước mặt (`minSteps = 0`, `em = 1.0`)** thay vì đi bộ 3 bước lên `(3, 3)` / `(3, 4)` để bắn *Dark Abbot* ở cuối sân `(7, 4)` (`minSteps = 3`, `em = 1.9`).
  - **Nhiệm vụ khi có thêm Dump mới**:
    1. Trích xuất toàn bộ cặp `(BattleRealmVO.map, InstantBattleResultVO.state.stepHistory)` từ các file dump mới.
    2. Chạy script tái hiện từng bước (`step-by-step replay`) để liệt kê mọi quyết định chọn mục tiêu `attackedUnitId` của cả Quân Ta lẫn Quân Địch ở từng bước `0..N`.
    3. Tối ưu hóa bộ hệ số `(w_em, w_kr, w_minSteps, w_dNow, w_slot)` sao cho tỷ lệ khớp từng bước chọn mục tiêu (`Step-Level Target Match Rate`) đạt **> 95%** trên toàn bộ các trận có bản đồ thật.

---

## Mảnh Ghép 2: Hồ Sơ "Bẫy Sát Thương Tỉnh Cao (`Ratio >= 1.8x`)" Cho Đủ 9 Tuần Relic Tourney

### Hiện trạng (`Engine v7.1`)
- Đã tích hợp `highStagePen` cho các đơn vị `light_ranged` không có phản đòn (`retal === 0`) khi đối đầu *Mist Walker / Wild Archer / Bandit* ở `squadRatio >= 1.75x`.
- **Điểm cần mở rộng qua 9 tuần Tourney**:
  - Mỗi kỳ Tournament xoay vòng qua 9 loại Cổ vật (Marble, Steel, Planks, Crystal, Scrolls, Silk, Elixir, Magic Dust, Gems) với các tổ hợp quái đặc thù:
    1. **Cặp Cận chiến tốc độ cao + Pháo xa**: *Hellhound / Cerberus (`mv=6, rng=1`)* + *Crazy Cannoneer (`rng=10`)* + *Thornrose Mage*.
    2. **Cặp Thiết giáp chống cung + Phù thủy**: *Vallorian Guard / Swamp Monster* + *Enchantress / Dark Abbot*.
    3. **Cặp Phản đòn tầm xa**: *Mist Walker (`ini=21, retal=1`)* + *Orc Deserter (`tg_hr, retal=1`)*.
  - **Nhiệm vụ khi có thêm Dump từng tuần**:
    - Đo ngưỡng **One-Shot / Two-Shot Threshold** thực tế ở Tỉnh 25–40 (`Ratio 1.8x – 2.2x`) cho từng loại tuần.
    - Cập nhật bảng trọng số tương ứng vào `score_unit_pair` / `eval_lineup` và ngưỡng cảnh báo **`⚠️ RỦI RO CAO — NÊN ĐÀM PHÁN (CATER)`**.

---

## Mảnh Ghép 3: Tự Động Hóa Đối Chiếu "Zero-Noise Ground Truth" (`Map + stepHistory`)

### Hiện trạng (`Userscript v6.7.2` + `benchmark_dump.py`)
- `elvenar-radar.user.js` (`v6.7.2`) đã tự động bắt ma trận `BattleMapVO.tiles[x][y]` khi người chơi vào trận Đánh tay và giữ khóa `trackedEncounter.obstacles` sau khi Đầu hàng (`BattleService.surrender`).
- `tools/benchmark_dump.py` đã tự động ghép cặp gói tin `BattleRealmVO` (chứa bản đồ thật) với `InstantBattleResultVO` (chứa kết quả và 40 bước đi thật của trận Auto ngay sau đó).
- **Quy trình chạy kiểm định tự động mỗi khi có Dump mới**:
  ```bash
  python "D:\ElvenarAuto\elvenar-dashboard\tools\benchmark_dump.py" "<đường_dẫn_file_dump_mới.json>"
  python "D:\ElvenarAuto\elvenar-dashboard\tools\verify_stage2_pipeline.py"
  ```

---

## Hướng Dẫn Thu Thập Dữ Liệu Tối Ưu Cho Người Chơi (Zero-Loss Scouting)

1. **KHÔNG CẦN cho lính đi đến chết hoặc cảm tử trong trận Đánh tay**:
   - Khi mở màn hình Đánh tay (`BattlefieldService.start`), **100% bản đồ vật cản (`BattleMapVO.tiles[8][9]`)** đã được gửi về ngay giây đầu tiên.
   - Toàn bộ 30–40 bước di chuyển và bắn nhau của cả 5 đạo địch lẫn 5 đạo ta **đã có sẵn 100% trong gói tin Đánh Auto (`InstantBattleResultVO.state.stepHistory`)** khi bạn ra ngoài bấm Auto-Battle!
   - Việc cho 1 lính đi đến chết trong Đánh tay vừa làm bạn **tốn quân vô ích**, vừa chỉ ghi lại cách địch vây đánh 1 đạo đơn lẻ ở `(0,4)` (không phản ánh đúng cách địch di chuyển khi gặp đủ 5 đạo quân của bạn ở `(0,2)..(0,6)` trong trận Auto).
2. **Cách Soi Map Không Mất 1 Giọt Máu (0% Loss)**:
   - Chọn **1 đạo quân có `Initiative` cao nhất** (như **Ranger** `Ini=20`, **Dryad** `Ini=19`, **Blossom Mage** `Ini=19`, hoặc **Elite Archer** `Ini=18`) bấm vào trận Đánh tay.
   - Ngay khi bản đồ hiện ra, bấm **Đầu hàng (`Surrender`)** ngay lập tức → **Không mất dù chỉ 1 lính!**
   - *(Mẹo riêng khi địch có **Sneaky Mist Walker** `Ini=21`)*: Vì *Mist Walker* là quái duy nhất trong game có `Ini=21` (luôn bắn 1 phát ở Bước 0 trước khi trao quyền điều khiển), khi gặp *Mist Walker*, nếu muốn Soi Map hãy đưa **1 đạo Senior Orc Strategist (`tg_hr`) hoặc Granite Golem (`eb_hr`)** có giáp kháng cung `-60%..-80%`, hoặc nếu không cần soi map ở các tỉnh thấp thì bấm Auto luôn.
