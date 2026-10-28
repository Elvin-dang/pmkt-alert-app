# Changelog

Mỗi phiên bản ghi rõ: **Mới**, **Thay đổi**, **Sửa lỗi**. Bản phát hành sẽ không build nếu thiếu mục cho phiên bản đó.

## v0.1.7 – 28/10/2026
### Mới
- **Lead / Thành viên.** Lead chạy dữ liệu, duyệt kết quả rồi bấm **Tải lên cho nhóm**. Thành viên chỉ xem: không chạy, không sửa, không góp ý, không Copy Message, không xuất Excel.
- **Mỗi thành viên chỉ thấy phần PIC của mình.** File báo cáo `.pmkt` được nén, mã hoá riêng cho từng thành viên và ký bởi Lead; app chỉ mở được file có chữ ký đúng và có phần dành cho mình. Dashboard của thành viên chỉ có điểm và xu hướng của chính họ (không có bảng xếp hạng).
- Nơi lưu báo cáo chung: **Supabase Storage** (Lead đăng nhập để tải lên, thành viên chỉ đọc) hoặc **thư mục chia sẻ** (OneDrive / SharePoint / ổ mạng). File tự đặt tên theo ngày giờ tải lên và không bao giờ ghi đè; thành viên bấm **Làm mới** rồi chọn báo cáo muốn xem.
- Thiết lập: Lead tạo nhóm → gửi **mã thiết lập** cho thành viên → thành viên gửi lại **mã thành viên** → Lead gán mã đó với PIC ở Cài đặt → Nhóm. Có thể xuất / nhận **khoá Lead** (file có mật khẩu) để chuyển sang máy khác.
- Nhấp đúp file `.pmkt` trên Windows sẽ mở bằng app.
- **Tiếng Anh / Tiếng Việt:** nút EN/VI trên thanh trên cùng đổi ngôn ngữ giao diện. Ngôn ngữ tin nhắn Claude viết cho PIC vẫn chỉnh ở Cài đặt → Văn phong.
- **Tiến trình chi tiết + thời gian còn lại:** từng PIC hiện bước đang làm (viết nháp → kiểm tra số liệu → biên tập) và số phần đã xong; thời gian còn lại ước tính theo các lần chạy trước và chính xác dần sau mỗi lần chạy.
### Thay đổi
- Chạy xong không tự chia sẻ nữa – Lead xem lại rồi mới tải lên.
- Kiểm tra quyền ở cả phía app (không chỉ ẩn nút): thao tác của Lead bị từ chối ở chế độ Thành viên.

## v0.1.6 – 27/10/2026
Bản này gồm toàn bộ thay đổi của v0.1.4 và v0.1.5 (hai bản đó build lỗi nên chưa từng phát hành).
### Mới
- Hỗ trợ **mô hình chấm điểm v3** (file Alert_Logic có trọng số w1–w6): phạm vi theo Team Label, khung Department (regime CÒN ROOM / VƯỢT), điểm 6 yếu tố cho từng PIC và PL, chốt chặn Excess$ vs Dept – khớp chính xác file v3. App tự nhận biết file dùng mô hình nào.
- Kết quả hiện khung Department, action + điểm của PIC, cột Điểm; bằng chứng cho cả PIC. SCALE UP hiển thị màu xanh lá.
- File đầu vào có thể là **.csv** hoặc **.xlsx** (trộn được). Tracking dạng CSV gồm 3 file: raw_sso_us, Product Info, KPI (INELIGIBLE ASIN tuỳ chọn). CSV đọc nhanh hơn ~4 lần. Hỗ trợ phân cách , ; tab, có/không BOM, ngày 2026-10-25 hoặc 25/10/2026.
- File Alert_Logic có lỗi không còn làm dừng lần chạy: app dùng giá trị dự phòng, liệt kê từng lỗi theo ô; Claude đánh giá lỗi nào nghiêm trọng / nên sửa / bỏ qua được kèm hướng dẫn sửa.
- Nút **Dừng** khi đang chạy: dừng ngay các lệnh Claude, vẫn giữ đầy đủ kết quả rule.
- Cập nhật app chạy ngầm, không còn mở cửa sổ terminal; nếu lỗi sẽ tự mở lại bản cũ và ghi `update.log`.
- Cửa sổ "Có gì mới" tự hiện một lần sau mỗi lần cập nhật; ghi chú phát hành lấy từ CHANGELOG.
### Sửa lỗi
- Nút Dừng trên Windows dừng được cả Claude cài bằng npm (dừng toàn bộ tiến trình con).
### Lưu ý
- Máy đang dùng v0.1.1–v0.1.3 cần **tải thủ công bản này một lần** (cơ chế cập nhật cũ có lỗi). Từ bản này trở đi cập nhật tự động bình thường.
- File logic (Alert_Logic) vẫn phải là .xlsx.

## v0.1.5 – 27/10/2026
- Không phát hành (build lỗi) – nội dung nằm trong v0.1.6.

## v0.1.4 – 27/10/2026
- Không phát hành (build lỗi) – nội dung nằm trong v0.1.6.

## v0.1.3 – 27/10/2026
### Mới
- Icon mới cho app.
- File tải về tên cố định `PMKT-Alert.exe` (số phiên bản xem trong app).
### Sửa lỗi
- Báo lỗi rõ ô nào trong file logic bị trống / là công thức chưa lưu, thay cho lỗi `float() … NoneType`.
- Nhận đúng file logic tên kiểu `…_v3`; luôn dùng đúng file logic người dùng chọn.

## v0.1.2 – 27/10/2026
### Mới
- Dashboard đội: scorecard từng PIC, biểu đồ, xu hướng theo tuần, nhận xét của Claude.
- Bằng chứng cho mỗi kết quả: công thức, ô ngưỡng trong Alert_Logic, file › sheet › cột › dòng Excel.
- Lọc và sắp xếp kết quả; chế độ phân tích kỹ 5 bước.
- Xưng hô riêng cho từng PIC và "Viết lại với Claude"; ghi chú cho Claude; giới hạn bộ nhớ app.
- Chọn file .xlsx trực tiếp hoặc kéo thả; nút cài / đăng nhập Claude Code.

## v0.1.1 – 27/10/2026
- Bản phát hành đầu tiên chạy được trên Windows.

## v0.1.0 – 27/10/2026
- Bản thử (build lỗi, không phát hành).
