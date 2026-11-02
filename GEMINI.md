# Elvenar Live Radar - Auto Git Push Rule

Mỗi khi có bất kỳ chỉnh sửa hoặc cập nhật nào trong dự án **Elvenar Live Radar**:

1. **Đồng bộ song song**:
   - Khi chỉnh sửa script Tampermonkey, luôn giữ đồng bộ cả 2 file:
     - `D:\ElvenarAuto\Elvenar Telegram Production Live Dashboard (Strict Single Message & Auto-Pin)-5.2.user.js`
     - `D:\ElvenarAuto\elvenar-dashboard\elvenar-radar.user.js`
   - Khi chỉnh sửa WebApp Dashboard: cập nhật file `D:\ElvenarAuto\elvenar-dashboard\index.html`.

2. **Bắt buộc Tự Động Commit & Push**:
   - Sau mỗi lần chỉnh sửa (cả script lẫn dashboard), Agent PHẢI tự động thực thi ngay lệnh:
     ```bash
     git -C "D:\ElvenarAuto\elvenar-dashboard" add -A
     git -C "D:\ElvenarAuto\elvenar-dashboard" commit -m "<Mô tả chi tiết thay đổi>"
     git -C "D:\ElvenarAuto\elvenar-dashboard" push origin main
     curl -s "https://purge.jsdelivr.net/gh/phusi319/elvenar-dashboard@main/elvenar-radar.user.js"
     ```
   - Đảm bảo GitHub Pages, link Raw và jsDelivr CDN của script luôn cập nhật bản mới nhất.

3. **Tăng Version Script để Tampermonkey Auto-Update**:
   - Khi sửa `elvenar-radar.user.js`, luôn tăng giá trị `@version` (ví dụ: `6.1.0` -> `6.1.1`) để Tampermonkey trên trình duyệt tự động cập nhật mà không cần cài lại thủ công.
   - Script sử dụng CDN jsDelivr (`cdn.jsdelivr.net`) kết hợp Purge API (`purge.jsdelivr.net`) để nhận cập nhật tức thì (0s delay), không bị dính cache 5 phút của GitHub.
