# Elvenar Radar — Battle AI Dump Benchmark & Simulation Suite

Công cụ phân tích độc lập (Self-contained CLI Suite) dùng để kiểm thử, phân tích dữ liệu thực tế từ các file dump JSON của game và chạy giả lập thuật toán Auto-Battle Advisor.

---

## 🎯 Tính Năng Chính

1. **Trích xuất dữ liệu trận đấu tự động**:
   - Quét toàn bộ các gói tin `InstantBattleResultVO` trong file JSON dump.
   - Đọc chính xác 5 vị trí quân địch (S1..S5), vị trí quân ta, Squad Size, HP, Damage, Initiative, Movement, Range và các buff chủ động.
   - Tự động nhận diện City Health Buff (Sanctuary / Monastery AW) và Military Attack Buffs.

2. **Giả lập Auto-Battle chuẩn xác theo cơ chế Elvenar**:
   - Chạy engine chiến đấu theo lượt (Turn-based combat up to 15 rounds).
   - Thứ tự đánh theo Initiative giảm dần (quân ta đi trước nếu bằng Initiative).
   - Cơ chế tầm bắn, phản công (Retaliation counter), sát thương suy giảm theo số lượng lính còn lại (Squad attrition), và khả năng phòng thủ / miễn nhiễm.

3. **Bảng xếp hạng sinh tồn thực tế (Empirical Unit Survival Ranking)**:
   - Thống kê tỷ lệ sống sót, số lần chọn, tỷ lệ tổn thất trung bình và số lần bị quét sạch (Wipeout 100%) của từng loại quân trong toàn bộ các trận đã đánh.

4. **Đối chiếu Benchmark: Thực Tế vs Đề Xuất Advisor**:
   - So sánh từng trận giữa kết quả thực tế người chơi đánh và kết quả giả lập theo thuật toán đề xuất của bản đang chạy (xem mục "Số hiện hành" bên dưới).
   - Thống kê Win Rate, Tỷ lệ tổn thất trung bình (Average Casualties), và Phân bổ tổn thất theo từng phân khúc (<15%, 15-30%, 30-50%, >=50%).

---

## 🚀 Hướng Dẫn Sử Dụng

### 1. Chạy với file dump mới nhất (Tự động phát hiện)
Nếu không truyền tham số, công cụ sẽ tự động tìm và chạy file `.json` mới nhất trong thư mục `D:\ElvenarAuto\Batte AI Data\` hoặc thư mục gốc:
```bash
python tools/benchmark_dump.py
```

### 2. Chỉ định file dump cụ thể
```bash
python tools/benchmark_dump.py "D:\ElvenarAuto\Batte AI Data\(tourney 6 stars) )elvenar_debug_dump_live_2026-11-05T22-34-01-612Z.json"
```

---

## 📌 Số hiện hành (v7.9.2, phát hành 2026-11-14)

- **Engine v7.9.2** = v7.9.1 + sửa lỗi: không đề xuất quân đã hết kho, chấm đa đợt Python khớp JS, trận đa đợt dưới 5 slot, làm tròn Python khớp JS. Trên 238 trận giải đấu thật, đội hình đề xuất không đổi so với v7.9.1.
- **Simulator giữ nguyên như v7.9.1.** Sai số so với trận thật (MAE, đúng đội hình người chơi đã đánh, 238 trận một đợt, có vật cản): **10.01 điểm %**; khớp thắng/thua 228/238.
- Các số thắng/tổn thất của đội hình do Engine đề xuất là do chính Simulator chấm, không phải kết quả đánh thật.
- Userscript đi kèm: 6.7.7.

---

## 📊 Kết Quả Tham Chiếu Mẫu (31 Trận Tourney 6 Sao)

> Khối mẫu dưới đây là lần chạy cũ bằng Advisor v6.5.2, giữ lại chỉ để minh họa định dạng đầu ra. Đây KHÔNG phải số của bản hiện hành.

```text
================================================================================
OVERALL PERFORMANCE SUMMARY: ACTUAL PLAYED vs ADVISOR v6.5.2
================================================================================
Metric                     | Actual Played      | Advisor v6.5.2 Simulated
--------------------------------------------------------------------------------
Win Rate                   | 30/31 ( 96.8%)    | 31/31 (100.0%)
Average Casualties         |  32.0%             |  22.6% (Giảm 9.4% thương vong)

CASUALTY DISTRIBUTION BRACKETS:
Bracket                    | Actual Played      | Advisor v6.5.2    
--------------------------------------------------------------------------------
< 15% (Flawless)           | 10 (32.3%)         | 11 (35.5%)
15% - 30% (Light)          |  6 (19.4%)         | 15 (48.4%)
30% - 50% (Moderate)       |  9 (29.0%)         |  3 ( 9.7%)
>= 50% / Defeat            |  6 (19.4%)         |  2 ( 6.5%)
================================================================================
```

---

> [!WARNING]
> Bảng trên so **kết quả giả lập** của Advisor với **kết quả thật** của người chơi. Đây chưa phải phép so sánh công bằng. Audit 2026-11-07 (bản cũ) đo sai số MAE 12.8 điểm % so với thực tế; số hiện hành ở mục "Số hiện hành". Xem `docs/BATTLE_ENGINE_AUDIT_ROADMAP.md`.

## 🧪 Audit độ chính xác Simulator (Ground-truth `stepHistory`)

```bash
python tools/audit_engine_fidelity.py                    # mọi dump trong ../Batte AI Data
python tools/audit_engine_fidelity.py a.json b.json      # chỉ định file
```

Công cụ này replay nhật ký trận thật (`InstantBattleResultVO.state.stepHistory`) để kiểm định lưới hex, di chuyển, phản đòn, AI chọn mục tiêu, debuff và chướng ngại vật. Sau đó chạy simulator với **đúng đội hình người chơi đã đánh** để đo MAE, Pearson và mức khớp Thắng/Thua. Mỗi phase trong lộ trình phải cải thiện các KPI này.

---

## 🔄 Khi Có Dữ Liệu Dump Mới

Khi bạn xuất file dump mới (Tourney các tuần khác hoặc Spire):
1. Đặt file `.json` vào thư mục `D:\ElvenarAuto\Batte AI Data\`.
2. Chạy `python tools/benchmark_dump.py`.
3. Công cụ sẽ tự động xuất báo cáo đầy đủ, giúp phát hiện ngay các trận đấu bất thường hoặc các điểm cần tinh chỉnh thuật toán.
