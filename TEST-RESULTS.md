# Kết quả chạy lại toàn bộ — 21/10/2026

- 45/45 kiểm thử chức năng web đạt trong database SQLite tạm riêng (56,28 giây).
- 21/21 kiểm thử thuật toán bổ sung đạt (0,27 giây): NN/GA/PSO, hoán vị hợp lệ, ma trận bất đối xứng, 1/2/6 điểm, giá trị chi phí đối chiếu độc lập và cận chính xác cho dữ liệu nhỏ, tái lập seed, hội tụ, Haversine/Euclid, đường mở/đóng, mục tiêu thời gian/quãng đường, nhiều seed, quy đổi đơn vị OSRM và từ chối điểm không thể nối đường bộ. Không khẳng định GA/PSO tìm tối ưu toàn cục.
- Tổng 66/66 ca tự động đạt qua hai lượt kiểm thử.
- JavaScript: mọi file vượt node --check. Python phân tích cú pháp đạt. HTML không trùng ID; tham chiếu ID trực tiếp hợp lệ.
- SQL Server thật: kiểm tra tích hợp không xóa dữ liệu đạt trong database mới GiaoGonShippingValidation_dceafe7d441548d4. Đã xác minh kiện/phí/giữ giá khi sửa liên hệ, giao có ảnh, quyền xem ảnh, COD/phí, nộp phiếu, xác nhận không lặp, trả COD, hoàn phí, tra cứu, thông báo và QR.
- Kiểm tra SQL thêm: lập chuyến chạy GA/PSO/NN thật, xuất CSV, bắt đầu chuyến, giao thất bại, chuyển hoàn, chặn nhân viên xác nhận nhận kho, Admin nhận kho, kết thúc chuyến và loại COD đơn hoàn khỏi báo cáo đều đạt. Kịch bản ban đầu dừng vì kỳ vọng HTTP 201 trong khi API lập chuyến trả 200; sửa kỳ vọng và tiếp tục chính chuyến thử, không sửa ứng dụng.
- Web thật cổng 5006: đăng nhập và 15 trang/API/tài nguyên/xuất báo cáo đều trả 200. Không tạo đơn/giao dịch trong database vận hành.

## Phạm vi chưa xác minh

- Chưa kiểm thử trực quan thao tác trình duyệt, điện thoại và cách bố trí màn hình.
- Không gọi dịch vụ OSRM công cộng hoặc tải bản đồ trực tiếp trong lượt kiểm thử; đã kiểm tra tích hợp đường bộ bằng dữ liệu giả lập. Tình trạng dịch vụ Internet bên ngoài chưa được xác nhận.
- Đây không phải kiểm thử tải, kiểm toán bảo mật toàn diện hoặc thử phục hồi backup.
- Không chạy bộ fixture xóa/reset SQL QA; kiểm thử SQL dùng dữ liệu thêm mới trong database riêng. Bộ 66 ca tự động chạy trên SQLite riêng, không được mô tả là 66 ca đều chạy SQL Server.
