# Triển khai GiaoGọn trên Render

## Điều kiện bắt buộc

SQL Server cục bộ `.\SQLEXPRESS` và Windows Authentication không dùng trực tiếp từ Render. Cần database SQL Server/Azure SQL được phép nhận kết nối từ dịch vụ Render, với SQL Authentication và TLS. Cấu hình firewall theo địa chỉ outbound của dịch vụ; không mở toàn bộ Internet. Không thay SQL Server bằng SQLite.

Tạo database trước; ứng dụng tạo các bảng còn thiếu khi khởi động. Database mới không tự có tài khoản/đơn hàng từ máy cá nhân. Nếu cần chuyển dữ liệu, phải thực hiện quy trình di chuyển riêng.

## Triển khai bằng giao diện web

1. Đăng nhập https://dashboard.render.com/.
2. Chọn New → Blueprint và repository `kiet62/giaogon-delivery`, nhánh `main`.
3. Render đọc `render.yaml`: Web Service Docker, gói Free, khu vực Singapore.
4. Điền biến bí mật `SQLSERVER_CONNECTION_STRING` trong Render; tuyệt đối không commit chuỗi thật lên GitHub.
5. Xác nhận tạo dịch vụ sau khi cấu hình database hợp lệ. Theo dõi build/deploy đến trạng thái Live.
6. Mở URL Render, tạo Admin đầu tiên ngay nếu database trống. Không công bố link đăng ký trước khi tạo Admin. Database local và cloud độc lập.

Nếu dùng New → Web Service thay Blueprint: chọn Docker, nhánh main; thêm `SECRET_KEY` ngẫu nhiên ổn định, `COOKIE_SECURE=1` và connection string trước khi deploy.

## Mẫu chuỗi kết nối (chỉ là placeholder)

```text
DRIVER={ODBC Driver 18 for SQL Server};SERVER=tcp:YOUR_HOST,1433;DATABASE=YOUR_DATABASE;UID=YOUR_SQL_USER;PWD={YOUR_PASSWORD};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=15;
```

Dùng connection string chính xác từ nhà cung cấp, có chứng thư hợp lệ. Container cài ODBC Driver 18 từ Microsoft; không dùng Driver 17 của Windows. Container chạy Gunicorn, nghe `0.0.0.0:$PORT`; `/login` là health check. Secret phiên ổn định do Render tạo; cookie chỉ gửi qua HTTPS.

Đây là cấu hình triển khai, không phải xác nhận dịch vụ đã Live. Không có SQL Server được truy cập từ Render thì ứng dụng sẽ không khởi động. Gói Free có giới hạn tài nguyên; kiểm tra gói hiện hành của Render trước khi vận hành. File ảnh và dữ liệu nghiệp vụ được lưu SQL Server, không phụ thuộc ổ đĩa tạm của container.

Tham khảo: https://render.com/docs/deploy-flask và https://render.com/docs/blueprint-spec.
