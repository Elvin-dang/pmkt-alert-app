# Changelog

Mỗi phiên bản ghi rõ: **Mới**, **Thay đổi**, **Sửa lỗi**. Bản phát hành sẽ không build nếu thiếu mục cho phiên bản đó.

## v0.1.7 – 28/10/2026
### Mới
- **Đăng nhập nhóm bằng email** (Supabase): nhập email → nhận mã 6 số → đăng nhập. Không mật khẩu, không phải gửi mã qua lại.
- **Lead tạo và quản lý tài khoản PIC** ở Cài đặt → Nhóm: email, tên, PIC, vai trò (Lead / Thành viên); đổi PIC, khoá, xoá có hiệu lực ngay. Chỉ email được Lead thêm mới đăng nhập được.
- **Thành viên chỉ xem, và chỉ phần PIC của mình:** không chạy, không sửa, không góp ý, không Copy Message, không xuất Excel. Dashboard chỉ có điểm và xu hướng của chính họ (không có bảng xếp hạng). Quyền được máy chủ Supabase kiểm tra, không chỉ ẩn nút trong app.
- **Tải lên cho nhóm:** Lead xem lại kết quả rồi bấm tải lên. Mỗi PIC một file `.pmkt` riêng, nén + mã hoá chỉ cho người của PIC đó, ký bởi Lead; tên theo ngày giờ, không bao giờ ghi đè. Thành viên bấm **Làm mới** rồi chọn báo cáo.
- Xuất / nhập **khoá Lead** (file có mật khẩu) để chuyển sang máy khác.
- **Tiếng Anh / Tiếng Việt:** nút EN/VI trên thanh trên cùng. Ngôn ngữ tin nhắn Claude viết cho PIC vẫn chỉnh ở Cài đặt → Văn phong.
- **Tiến trình chi tiết + thời gian còn lại:** từng PIC hiện bước đang làm (viết nháp → kiểm tra số liệu → biên tập) và số phần đã xong; thời gian còn lại học từ các lần chạy trước.
### Thay đổi
- Chạy xong không tự chia sẻ – Lead duyệt rồi mới tải lên.
### Lưu ý
- Lead cần thiết lập Supabase một lần (hướng dẫn trong hộp thoại đăng nhập → "Lead lần đầu").

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
