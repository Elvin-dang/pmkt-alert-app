# Changelog

Mỗi phiên bản ghi rõ: **Mới**, **Thay đổi**, **Sửa lỗi**. Bản phát hành sẽ không build nếu thiếu mục cho phiên bản đó.

## v0.1.4 – 27/10/2026
### Mới
- Cập nhật app chạy ngầm, không còn mở cửa sổ terminal; nếu lỗi sẽ tự mở lại bản cũ và ghi `update.log`.
- Cửa sổ "Có gì mới" tự hiện một lần sau mỗi lần cập nhật.
- Nút **Dừng** khi đang chạy: dừng ngay các lệnh Claude, vẫn giữ đầy đủ kết quả rule.
- Hỗ trợ **mô hình chấm điểm v3** (file Alert_Logic có trọng số w1–w6): phạm vi theo Team Label, khung Department (regime CÒN ROOM / VƯỢT), điểm 6 yếu tố cho từng PIC và PL, chốt chặn Excess$ vs Dept – khớp chính xác file v3. App tự nhận biết file dùng mô hình nào.
- Kết quả hiện khung Department, action + điểm của PIC, cột Điểm; bằng chứng cho cả PIC.
- SCALE UP hiển thị màu xanh lá.
- File Alert_Logic có lỗi không còn làm dừng lần chạy: app dùng giá trị dự phòng, liệt kê từng lỗi theo ô, và Claude đánh giá lỗi nào nghiêm trọng / nên sửa / bỏ qua được kèm hướng dẫn sửa.
- Đọc được file logic có bố cục khác (đổi thứ tự / tên mục), liệt kê các tham số app chưa dùng.
### Lưu ý
- Máy đang dùng v0.1.1–v0.1.3 cần tải thủ công bản này một lần (cơ chế cập nhật cũ có lỗi). Từ bản này trở đi cập nhật tự động bình thường.

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
