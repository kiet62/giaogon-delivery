# Kiểm tra ngày 21/10/2026

- Kết nối SQL Server `.\SQLEXPRESS` bằng Windows Authentication thành công; ODBC Driver 17.
- Database riêng `GiaoGonShipper` đã được tạo và có bảng vận hành. Không sửa database cũ.
- **12/12 kiểm thử đạt trên SQLite tạm**, dùng riêng cho test.
- **12/12 kiểm thử đạt trên Microsoft SQL Server thực**, database `GiaoGonShipper_QA_20261021` riêng. Không sử dụng database vận hành để kiểm thử dữ liệu.
- Các ca kiểm tra: bootstrap Admin chỉ một lần, CSRF, đăng nhập/hash, API chặn quyền, nhân viên không xem/sửa/export tài nguyên người khác, bắt buộc đổi mật khẩu tạm, khóa/reset hủy phiên, trạng thái đơn, lý do thất bại/giao lại, COD, conflict version, chuyến start/complete/cancel, ngăn một đơn thuộc hai chuyến hoạt động, CSV nguyên tử và không còn cài đặt nâng cao trong HTML.
- JavaScript app/portal vượt kiểm tra cú pháp; Python biên dịch thành công.
- Thuật toán GA/PSO/NN sử dụng lại phần đã kiểm thử từ bản trước. Kiểm thử portal dùng chế độ đường thẳng để độc lập Internet; không gọi OSRM trong bộ test quyền.
- Chưa kiểm tra trực quan các thao tác bằng trình duyệt. Cần xác minh thủ công giao diện theo vai trò, chọn tọa độ, lớp bản đồ và biểu đồ trên máy người dùng.
- Database vận hành chưa có mật khẩu mặc định; chủ ứng dụng tự tạo Admin đầu tiên ở màn hình khởi tạo.

Cập nhật đăng nhập/đăng ký: bỏ ô họ tên Admin, xác nhận mật khẩu, tài khoản đầu tiên Admin, các tài khoản sau luôn là Nhân viên dù cố gửi role=admin. Kiểm tra thêm CSRF, username trùng và hai trang tài khoản.

Bổ sung Admin: bộ kiểm thử tổng cộng 20 ca đạt trên SQLite tạm. 5 ca mới đều đạt trên SQL Server QA thực, gồm báo cáo ngày/COD, chặn Nhân viên, phân công hàng loạt, rollback khi conflict và sửa nhân viên. Phát hiện/sửa lỗi ODBC kết quả truy vấn chưa được đọc hết trước truy vấn tiếp theo; báo cáo hiện đọc hết kết quả trước khi truy vấn tiếp. Chưa xác minh trực quan trình duyệt.

Bổ sung Khách hàng: 26 kiểm thử đạt trên SQLite tạm; 6 ca mới đạt trên SQL Server QA thực. Kiểm tra tạo đơn gắn đúng người tạo, chống giả shipper/status/created_by, chặn truy cập chéo khách, theo dõi sau phân công/giao hàng, chỉ hủy trước phân công, Admin tạo/khóa khách và chặn quyền shipper/Admin. JavaScript customer/portal kiểm tra cú pháp thành công. Chưa kiểm tra trực quan trình duyệt.

Siết RBAC: 5 ca mới đạt trên SQL Server QA thật, gồm kiểm tra danh sách quyền endpoint, ma trận từ chối API theo role, endpoint mới bị chặn mặc định, giả mạo role ở session không nâng quyền và role không hợp lệ bị hủy phiên. Tổng bộ kiểm thử hiện có 31 ca. Đã thêm chặn chuyển tab ngoài quyền ở giao diện; chưa xác minh trực quan trình duyệt.

Hoàn thiện nghiệp vụ: 38/38 kiểm thử đạt trên SQLite tạm, gồm 7 ca mới về kiện hàng/phí, bảo vệ giá đã thu, ảnh xác nhận, phân quyền xem ảnh, hoàn hàng và đối soát không trùng. Sau thay đổi cuối, 13 kiểm thử kiện hàng/khách hàng chạy lại đều đạt. Các tham chiếu ID JavaScript đều tồn tại trong HTML, không trùng ID; kiểm tra cú pháp JS/Python đạt.

SQL Server: cách chạy pytest với reset dữ liệu QA bị bộ duyệt tự động từ chối. Đã thay bằng kiểm tra không phá hủy trong database mới GiaoGonShippingValidation_20261021_A: chỉ thêm dữ liệu xác minh, không xóa/reset bản ghi. Đã xác minh đặt đơn có phí/kiện, phân công, ảnh giao lưu VARBINARY và xem theo quyền, thu COD/phí người nhận, nộp phiếu, Admin nhận tiền, chặn xác nhận lặp; kiểm tra thêm hoàn hàng chỉ Admin nhận kho và tổng tiền đối soát. Tất cả thành công.

Nâng cấp database vận hành GiaoGonShipper: thêm 4 bảng mới, số tài khoản/đơn/chuyến trước và sau giữ nguyên. Không đặt lại mật khẩu hoặc thay vai trò. Chưa kiểm thử trực quan trên trình duyệt/điện thoại.


## Bổ sung sau rà soát — 21/10/2026

- **45/45 kiểm thử đạt trên SQLite riêng** (`tests/test_completion.py` thêm 7 ca). Gồm sửa số điện thoại không đổi phí kể cả phí đã thu; thay khối lượng tính lại phí chưa thu; đơn hoàn không còn COD cần thu; điều kiện trả COD, chống chi trùng; hoàn/giữ lại phí; quyền archive/thông báo/phiếu QR; phân trang không trùng/mất đơn.
- **SQL Server thật:** smoke không xóa dữ liệu đạt trong database mới `GiaoGonShippingValidation_20261021_B`. Đã kiểm tra giao hàng có ảnh, thu tiền, đối soát, trả COD, hoàn phí, sửa đơn giữ snapshot giá, tra cứu, thông báo đã đọc và ảnh QR. `deleted_rows=0`; không chạy fixture reset SQL QA.
- Nâng cấp database `GiaoGonShipper` chỉ thêm bảng `order_settlements`, `notification_reads`; trước/sau: 1 tài khoản, 0 đơn, 0 chuyến. Không đổi mật khẩu/vai trò.
- JavaScript vượt kiểm tra cú pháp; HTML không trùng ID và tham chiếu ID trực tiếp hợp lệ. Chưa xác minh trực quan bằng trình duyệt/điện thoại.
- Web được khởi động lại cổng 5006; đăng nhập Admin, HTML mới, archive, notifications, billing, history và static completion.js trả HTTP 200. Không tạo đơn/giao dịch trong database vận hành.
- Biên nhận ghi nhận khoản đã chi thực tế; chưa tích hợp ngân hàng, SMS/email hoặc GPS trực tiếp. QR chỉ chứa mã đơn, xem thông tin vẫn cần đăng nhập đúng quyền.


Chạy lại toàn bộ: 66/66 ca tự động đạt (45 chức năng + 21 thuật toán), SQL Server tích hợp và HTTP web đang chạy đạt. Chi tiết, giới hạn và database thử nằm trong TEST-RESULTS.md.
