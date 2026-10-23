# GiaoGọn — Admin / Nhân viên / Khách hàng · Microsoft SQL Server

Ứng dụng mới dành cho điều phối và giao hàng, sử dụng **SQL Server thực**, Flask, SQLAlchemy/pyodbc và GA/PSO/NN. Không có chế độ âm thầm quay về SQLite. Các cài đặt nâng cao đã bỏ khỏi giao diện; tham số thuật toán được cố định phía máy chủ.

## Trên máy hiện tại

Đã kiểm tra kết nối Windows Authentication tới `.\SQLEXPRESS`, driver **ODBC Driver 17 for SQL Server**. Database riêng `GiaoGonShipper` đã được tạo; các database khác không thay đổi.

Mở **http://127.0.0.1:5006/**. Trang tài khoản có hai tab Đăng nhập / Đăng ký. Đăng ký chỉ cần tên đăng nhập, mật khẩu và nhập lại mật khẩu; không có ô họ tên Admin. Tài khoản đăng ký đầu tiên là Admin, mọi tài khoản đăng ký tiếp theo là Khách hàng. Không có mật khẩu mặc định. Bước khởi tạo đóng lại sau khi có tài khoản đầu tiên.

## Cài trên máy khác

Cần Python 3.10+, SQL Server (Express cũng được) đang chạy và Microsoft ODBC Driver 17 hoặc 18 for SQL Server.

1. Chạy `initialize.sql` bằng SSMS hoặc `sqlcmd` để tạo database mới.
2. Sao chép `.env.example` thành `.env`. Điền tên server/instance, database và driver đúng với máy của bạn. Windows Authentication dùng tài khoản Windows chạy ứng dụng. Với SQL Authentication, đặt connection string trong `.env`; không gửi mật khẩu vào chat hoặc đưa `.env` lên Git.
3. Nhấp đúp **start.bat**, hoặc chạy thủ công:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

4. Mở http://127.0.0.1:5006 và tạo Admin đầu tiên.

Trên Linux/macOS dùng `.venv/bin/python`, và cấu hình SQL Authentication hoặc Windows/Kerberos phù hợp. Đừng dùng `SQLITE` cho môi trường thật. SQLAlchemy chỉ cho phép SQLite trong hàm app factory với `testing=True` để chạy test độc lập.

Nếu gặp lỗi kết nối: kiểm tra dịch vụ SQL Server, tên instance, quyền Windows/SQL login, driver ODBC và database. Driver 18 có thể chọn trong `.env`. Cấu hình hiện tại tin chứng thư của SQL Server cục bộ; khi triển khai server khác cần chứng thư hợp lệ và điều chỉnh connection string. Không cần mở SQL Server ra Internet để chạy trên máy hiện tại.

## Phân quyền

| Chức năng | Admin | Nhân viên |
|---|---|---|
| Tạo tài khoản nhân viên, khóa/mở, đặt mật khẩu tạm | Có | Không |
| Quản lý điểm lấy hàng chung | Có | Chỉ xem |
| Tạo/sửa đơn, nhập CSV, phân công, hủy đơn | Có | Không |
| Xem đơn và báo cáo | Toàn bộ | Chỉ đơn được giao cho mình |
| Lập chuyến GA/PSO/NN | Cho nhân viên được chọn | Từ đơn của mình |
| Xem tuyến, CSV chuyến, bắt đầu/kết thúc chuyến | Toàn bộ | Chỉ chuyến của mình |
| Cập nhật lấy hàng, đang giao, thành công/thất bại | Có | Chỉ đơn của mình |
| Xác nhận thu COD | Có | Chỉ đơn đã giao của mình |
| Đổi mật khẩu và thông tin cá nhân | Của mình | Của mình |

Quyền được kiểm tra **ở API**, không chỉ ẩn nút. Mật khẩu băm scrypt; đăng nhập dùng cookie HttpOnly/SameSite, token CSRF cho mọi yêu cầu thay đổi dữ liệu. Khóa/reset tài khoản hủy phiên cũ; mật khẩu tạm bắt buộc đổi trước khi sử dụng. Giới hạn 10 lần đăng nhập sai/5 phút theo IP trong tiến trình hiện tại. Có đăng ký tài khoản Khách hàng; người đăng ký không được tự chọn quyền Admin. Quyền Admin chỉ cấp cho tài khoản đầu tiên khi database chưa có người dùng.

## Quy trình sử dụng

### Admin

1. Tạo Admin đầu tiên, đăng nhập.
2. Vào **Nhân viên**: tạo họ tên, username và mật khẩu tạm (từ 8 ký tự).
3. Tạo đơn trong **Đơn hàng**: người nhận, điện thoại, địa chỉ mô tả, tọa độ chọn trên bản đồ hoặc nhập tay, thời gian dừng, COD và ghi chú. Chọn nhân viên ngay khi tạo hoặc phân công sau.
4. Trong **Lập chuyến**, chọn nhân viên; các đơn đủ điều kiện hiện ra. Chọn tối đa 25 đơn, nguồn khoảng cách, mục tiêu và có/không quay về kho. Bấm tìm tuyến.
5. Xem tiến độ tại **Chuyến giao**, đơn giao thất bại và COD tại **Đơn hàng**. Xem nhật ký từng đơn để biết ai đã cập nhật.

### Nhân viên

1. Đăng nhập bằng tài khoản được cấp; đổi mật khẩu tạm.
2. Vào **Chuyến giao** xem chuyến được phân công hoặc tự lên tuyến từ đơn được giao.
3. Bấm **Bắt đầu lấy hàng**: đơn ở trạng thái đã phân công chuyển sang đã lấy hàng.
4. Vào **Đơn hàng**, bấm bắt đầu giao, mở chỉ đường hoặc gọi người nhận. Cập nhật giao thành công và đã thu COD, hoặc thất bại kèm lý do. Có thể giao lại đơn thất bại.
5. Chỉ kết thúc chuyến sau khi tất cả đơn đã giao hoặc thất bại. Không thể kết thúc khi vẫn có đơn đang chờ/đang giao.
6. Xem lịch sử, xuất CSV trong phạm vi của mình; cập nhật số điện thoại/phương tiện ở Tài khoản.

## Quy tắc dữ liệu

- Luồng đơn: chờ phân công → đã phân công → đã lấy hàng → đang giao → đã giao / thất bại. Thất bại có thể giao lại. Admin chỉ hủy đơn chưa giao, không thuộc chuyến hoạt động.
- Đơn đã vào chuyến hoạt động không được phân công lại hoặc sửa vị trí. Một đơn chỉ có một chuyến hoạt động, được bảo vệ bằng unique filtered index ở SQL Server và kiểm tra version khi cập nhật.
- Admin chỉ hủy chuyến chưa bắt đầu. Hủy hoặc hoàn tất chuyến giải phóng các đơn khỏi chuyến hoạt động; lịch sử/snapshot vẫn giữ.
- Xác nhận COD có thể thực hiện khi giao thành công hoặc sau đó; COD chưa thu vẫn được thống kê. Có phiếu nộp tiền đối soát tại kho; đây là ghi nhận nghiệp vụ, không tự chuyển khoản ngân hàng.
- Nhập CSV UTF-8 với cột `name,address,lat,lon,phone,cod,service_minutes,note,shipper_id`. Bỏ cột tùy chọn nếu không dùng. Không nhập cột `shipper_id` thì đơn chờ phân công. Tối đa 100 dòng/file, kiểm tra nguyên tử: có dòng lỗi thì không ghi cả file. Mẫu tại `samples/orders.csv`.
- Nút thêm mẫu **thêm** 6 đơn mới, không xóa đơn cũ. Các bản SQLite của web trước vẫn giữ riêng và không tự nhập vào SQL Server để tránh gán nhầm người dùng; có thể nhập lại bằng CSV.
- Danh sách hiển thị tối đa 1000 đơn gần nhất, 100 chuyến gần nhất. Dữ liệu cũ không bị xóa; bản này chưa có phân trang lớn.

## Tuyến đường và thuật toán

Giữ nguyên GA/PSO random keys/NN của bản trước, tham số tự động cố định 60 cá thể/hạt, 150 vòng và seed 42/123/2026. Tham số gửi lén từ trình duyệt không được dùng. Hỗ trợ hành trình mở hoặc quay về kho.

Chế độ ước tính dùng Haversine, 25 km/h giả định; không phải quãng đường hoặc ETA đường bộ. Chế độ đường bộ gửi tọa độ tới OSRM công cộng sau xác nhận, dùng hồ sơ ô tô và không có giao thông trực tiếp. Khoảng cách ma trận OSRM nằm trên tuyến do dịch vụ chọn, không khẳng định đường ngắn nhất theo km tuyệt đối. Lỗi dịch vụ không tự chuyển thành đường thẳng. GA/PSO không bảo đảm tối ưu toàn cục. Một shipper, một kho; chưa xét tải trọng xe, giờ hẹn, nhiều điểm lấy hàng, GPS trực tiếp hoặc thông báo SMS. Ảnh xác nhận giao hàng đã được bổ sung.

## Database và mã nguồn

- `users`: tài khoản, vai trò, hash, trạng thái và phiên bản xác thực.
- `delivery_orders`: đơn hàng, nhân viên, tọa độ, trạng thái, COD, version.
- `delivery_plans`, `plan_orders`: chuyến, snapshot tuyến, liên kết đơn và khóa chuyến hoạt động.
- `order_events`: nhật ký cập nhật theo người dùng.
- `settings`: kho lấy hàng.

Tất cả bảng vận hành dùng Microsoft SQL Server. `models.py` định nghĩa bảng bằng SQLAlchemy; `app.py` xử lý xác thực/phân quyền và nghiệp vụ; `routing.py`/`algorithms.py` xử lý tuyến; `static/portal.js` và template chứa giao diện theo vai trò. Khóa ký phiên được tạo tại `instance/.session-key` hoặc biến `SECRET_KEY`; không đưa khóa này vào bản ZIP/Git. Không dùng mật khẩu mặc định.

## Kiểm thử

```powershell
.venv\Scripts\python -m pytest -q
```

Test mặc định dùng SQLite tạm rõ ràng, không thay database thật. Để kiểm tra Microsoft SQL Server thực, tạo database riêng có tiền tố `GiaoGonShipper_QA_` rồi chạy:

```powershell
$env:SHIPPER_TEST_SQLSERVER='GiaoGonShipper_QA_20261021'
.venv\Scripts\python -m pytest -q
```

**Chỉ dùng database QA**: bộ test xóa dữ liệu trong các bảng của database QA giữa các ca. Code từ chối tên database không có tiền tố bắt buộc. Test bao gồm bootstrap, CSRF, hash, phân quyền, truy cập trực tiếp tài nguyên người khác, đổi mật khẩu tạm, khóa/reset phiên, trạng thái giao hàng/COD, xung đột version, vòng đời chuyến và nhập CSV nguyên tử.

Ứng dụng phục vụ đồ án/cục bộ, chạy một tiến trình Flask. Trước triển khai Internet cần HTTPS, server WSGI, quản lý bí mật, backup SQL Server, phân trang, giới hạn request tập trung và quy trình vận hành phù hợp. Bản này chưa đẩy lên GitHub.

## Chức năng Admin bổ sung

Sau đăng nhập Admin, trang **Quản trị** mở mặc định. Có tổng quan trạng thái đơn, tỷ lệ đã giao, chuyến đang hoạt động, báo cáo hiệu suất/COD theo nhân viên và 20 nhật ký gần đây. Bộ lọc ngày dùng ngày tạo đơn theo UTC; số chuyến hoạt động và nhật ký là trạng thái hiện tại toàn hệ thống, không lọc theo ngày. Có thể xuất báo cáo nhân viên ra CSV.

Trong Đơn hàng, lọc theo nhân viên hoặc Chưa phân công, chọn nhiều đơn và bấm **Phân công các đơn đã chọn**. Tối đa 100 đơn/lần; tất cả đơn phải chưa giao/hủy/đang giao và không thuộc chuyến hoạt động. Giao dịch nguyên tử và version ngăn phân công dở dang hoặc ghi đè cập nhật mới.

Trong Nhân viên, nút **Sửa thông tin** cập nhật họ tên, điện thoại và phương tiện/biển số. Chức năng khóa/mở/reset mật khẩu cũ vẫn giữ. Các API báo cáo và phân công hàng loạt chỉ Admin được truy cập.

## Vai trò Khách hàng (customer)

Tài khoản tự đăng ký mới thuộc vai trò **Khách hàng** (trừ tài khoản đầu tiên khi database trống là Admin). Tài khoản Admin/Nhân viên hiện có không bị chuyển quyền. Admin cũng có thể tạo tài khoản Nhân viên hoặc Khách hàng qua mục Tài khoản; không cho tạo thêm Admin qua đăng ký công khai.

Khách hàng có trang **Đơn của tôi** riêng: tạo yêu cầu, nhập người nhận/điện thoại/địa chỉ/tọa độ/ghi chú/COD; tất cả đơn lấy cùng kho chung. Bản đồ chọn vị trí nằm ngay trong hộp tạo đơn. Trạng thái ban đầu luôn là chờ phân công, bất kể gửi thêm shipper_id/status/created_by qua API. Máy chủ tự ghi người tạo từ phiên đăng nhập.

Khách chỉ xem, lọc và xuất CSV các đơn mình tạo; xem lịch sử cập nhật, lý do giao thất bại và tình trạng COD. Trang tự tải lại mỗi 30 giây khi đang hiển thị, hoặc bấm Cập nhật trạng thái. Đây là cập nhật trạng thái nghiệp vụ, không phải GPS trực tiếp. Có thể hủy đơn của mình khi chưa phân công; sau phân công liên hệ Admin. Khách không được thay trạng thái giao hàng/thu COD, phân công, lập chuyến hoặc truy cập tài nguyên của khách khác.

SQL Server bổ sung cột nullable `delivery_orders.created_by` và index/FK tới users, tự nâng cấp khi khởi động. Script tham khảo tại `migrations/003_customer_owner.sql`. Đơn cũ giữ nguyên và không tự gán cho khách bất kỳ khi chưa xác định chủ sở hữu. Admin thấy người tạo đơn để điều phối. Không xóa dữ liệu hoặc đặt lại mật khẩu trong bản cập nhật.

## Giới hạn quyền theo vai trò

`permissions.py` là danh sách endpoint/phương thức được phép của từng role. API mới chưa khai báo trong danh sách bị từ chối mặc định, kể cả Admin; không dùng wildcard toàn quyền. Ngoài danh sách quyền, từng đơn/chuyến vẫn phải kiểm tra quyền sở hữu hoặc nhân viên được phân công.

| Thao tác | Admin | Nhân viên | Khách hàng |
|---|---|---|---|
| Quản lý tài khoản, kho, nhập mẫu/CSV, phân công, báo cáo toàn hệ thống | Có | Không | Không |
| Tạo yêu cầu giao | Có | Không | Có, luôn gắn tài khoản đang đăng nhập |
| Xem đơn, lịch sử đơn, xuất danh sách | Toàn bộ | Chỉ đơn được giao | Chỉ đơn tự tạo |
| Sửa nội dung/phân công/hủy nghiệp vụ | Theo quy tắc đơn | Không | Chỉ hủy yêu cầu chưa phân công |
| Tạo/xem/xuất/bắt đầu/kết thúc chuyến | Toàn bộ | Chỉ đơn/chuyến được giao | Không |
| Hủy chuyến chưa bắt đầu | Có | Không | Không |
| Cập nhật giao hàng, xác nhận COD | Có | Chỉ đơn của mình | Không |
| Thông tin cá nhân/đổi mật khẩu | Của mình | Của mình | Của mình |

Vai trò được đọc lại từ SQL Server ở mỗi yêu cầu; không tin role/is_admin do cookie hoặc JSON phía khách gửi. Tài khoản bị khóa hoặc có role không hợp lệ bị hủy phiên. Menu và chuyển trang trong giao diện dựa trên quyền do máy chủ trả về; yêu cầu API trái quyền trả 403. Truy cập mã đơn/chuyến của người khác trả 404 để không tiết lộ tài nguyên. Phiên hết hạn bị đưa về trang đăng nhập. Không thay vai trò/mật khẩu của các tài khoản đang dùng trong bản cập nhật này.

## Quy trình giao hàng mở rộng

### Kiện hàng và phí

Đơn mới có tên hàng, số kiện (1–1000), tổng khối lượng (0,1–100 kg), loại hàng, giá trị khai báo, người trả phí và phí giao. Khối lượng là tổng lô hàng, không nhân thêm với số kiện. Loại hàng dùng để phân loại, chưa có phụ phí riêng. Giá trị khai báo không tạo hợp đồng bảo hiểm.

Phí do máy chủ tính: phí cơ bản + km đường thẳng vượt mức bao gồm × đơn giá km + số kg vượt mức làm tròn lên × đơn giá kg; tổng làm tròn lên 1.000đ. Mặc định 15.000đ bao gồm 3 km/2 kg, thêm 3.000đ/km và 5.000đ/kg. Đây là biểu phí mẫu nội bộ, không phải giá dịch vụ thị trường. Admin đổi biểu phí ở Quản trị. Trình duyệt không được tự đặt shipping_fee; hệ thống kiểm tra lại quoted_fee và lưu snapshot lúc tạo. Không tự thay giá đơn cũ khi Admin đổi biểu phí. Đơn cũ chưa có kiện hàng có phí hiển thị 0, không tự truy thu.

Người gửi trả phí tại kho: chỉ Admin xác nhận thu. Người nhận trả phí: shipper xác nhận khi giao thành công hoặc sau khi đã giao. COD là tiền hàng thu hộ, tách khỏi phí giao. Thông tin kiện/phí đã thu không được sửa làm mất dấu khoản tiền đã ghi nhận.

### Bằng chứng giao hàng

Bấm Giao thành công sẽ mở biểu mẫu nhập người đã nhận, ảnh xác nhận và các khoản đã thực thu. Máy chủ bắt buộc đơn đang giao và có ảnh hợp lệ; không thể bỏ qua bằng API đổi trạng thái trực tiếp. Ảnh JPEG/PNG/WebP tối đa 3 MB/12 triệu điểm ảnh, được giải mã và chuẩn hóa JPEG (bỏ metadata), lưu trong SQL Server. Không lưu đường dẫn ảnh công khai. Chỉ Admin, nhân viên được phân công và khách tạo đơn mới xem được. Không sửa ảnh sau khi hoàn tất. Đây là bằng chứng ghi nhận, không phải xác minh danh tính độc lập/OTP.

### Hoàn hàng

Đơn thất bại có thể giao lại hoặc chuyển hoàn, bắt buộc có lý do. Khi đang chuyển hoàn, chỉ Admin xác nhận kho đã nhận lại hàng kèm biên nhận/ghi chú. Trạng thái trả về kho được phép kết thúc chuyến; chuyến đang có hàng chuyển hoàn chưa nhận lại không được kết thúc. Admin xử lý phí đã thu sau hủy/hoàn: nhập phần giữ lại và biên nhận chi thực tế; hệ thống ghi tiền hoàn bằng phí đã thu trừ phần giữ lại. Không tự chi tiền.

### Đối soát COD và phí

Mục Đối soát COD có danh sách tiền đủ điều kiện lập phiếu, phiếu đang chờ, tổng kho đã xác nhận và lịch sử. Chỉ đơn đã giao và thu đủ COD/phí người nhận được chọn vào phiếu. Phí người gửi trả tại kho không tính thành tiền nhân viên phải nộp. Một đơn chỉ nằm trong một phiếu đang chờ/đã xác nhận (unique filtered index trong SQL Server), ngăn ghi nhận hai lần. Phiếu cộng các số tiền nguyên bằng BigInteger.

Nhân viên gửi phiếu; Admin kiểm tra tiền thực tế rồi xác nhận hoặc từ chối kèm lý do. Sau từ chối, đơn được chọn lại vào phiếu mới; lịch sử phiếu cũ giữ nguyên. Không xác nhận hai lần. Admin có thể lập phiếu hộ nhân viên; người nhận tiền vẫn phải tự xác nhận. Có biên nhận trả COD cho khách tạo đơn sau khi kho xác nhận phiếu nộp tiền; không tự chuyển khoản ngân hàng.

Các bảng mới được tạo bổ sung: order_parcels, delivery_proofs, cod_remittances, cod_remittance_items. Không xóa bảng cũ hoặc thay mật khẩu. Backup SQL Server phải bao gồm dữ liệu ảnh trong bảng delivery_proofs. File ZIP không chứa tài khoản/dữ liệu vận hành.

### Giới hạn triển khai còn lại

Bản này hoàn thiện luồng nội bộ phục vụ đồ án, chưa thay thế một nền tảng giao hàng thương mại. Vẫn một kho chung/một shipper mỗi chuyến, chưa theo dõi GPS trực tiếp, cổng thanh toán/SMS, tự tìm tọa độ địa chỉ hoặc điều phối theo tải trọng/giờ hẹn. Trước vận hành Internet cần HTTPS, mật khẩu mạnh, backup/khôi phục được kiểm thử và máy chủ WSGI phù hợp.

### Kiểm tra SQL Server không xóa dữ liệu

Khuyến nghị dùng `scripts/verify_sqlserver.py` thay bộ pytest reset QA khi muốn xác minh SQL thực mà không xóa bản ghi. Tạo một database mới, tên bắt đầu `GiaoGonShippingValidation_`, rồi đặt `SQLSERVER_DATABASE` thành tên đó và chạy script bằng Python đã cài requirements. Script tạo dữ liệu xác minh mới, không DELETE/TRUNCATE, giữ dữ liệu kiểm tra lại trong database riêng. Không chạy trên database vận hành; nếu tái sử dụng database đã có tài khoản thì bước tạo Admin sẽ từ chối. File script dùng các tài khoản/mật khẩu mẫu chỉ phục vụ xác minh, không phải tài khoản của web thật.


## Cập nhật đối soát, tra cứu và thông báo

- **Giữ phí đã chốt:** sửa tên, điện thoại, địa chỉ mô tả hoặc ghi chú giữ nguyên phí/snapshot nếu tọa độ và kiện hàng không đổi. Đổi tọa độ hoặc kiện hàng chưa thu phí cần tính/xác nhận giá lại. Không sửa thông tin tính phí của đơn đã thu.
- **COD còn cần thu:** không bao gồm đơn hủy, đang chuyển hoàn và đã hoàn về kho; COD đã thu vẫn được giữ trong báo cáo thu tiền.
- **Trả COD cho khách:** Admin mở đơn đã giao → Ghi nhận trả COD cho khách. Chỉ thực hiện khi đơn của tài khoản khách, COD đã thu và phiếu nộp tiền được kho xác nhận. Nhập mã giao dịch/biên nhận thực tế. Hệ thống chốt số tiền bằng COD của đơn, chống ghi nhận lặp bằng khóa duy nhất và kiểm tra phiên bản. Khách xem biên nhận và thông báo trong đơn của mình. Đơn do Admin tạo không tự suy đoán người hưởng tiền.
- **Hoàn/giữ lại phí:** Admin mở đơn đã hủy hoặc đã hoàn về kho và có phí đã thu → Xử lý hoàn/giữ lại phí. Nhập số tiền giữ lại trong phạm vi phí gốc, lý do và mã biên nhận. Số hoàn = phí đã thu − phí giữ lại. Cho phép giữ toàn bộ (số hoàn 0) khi có lý do. Phiếu bất biến, không ghi đè khoản đã thu. Chưa có nghiệp vụ thu thêm phí hoàn vượt phí gốc hoặc sửa sai biên nhận đã chốt.
- **Tra cứu tất cả đơn:** nút đầu trang, tìm theo mã/tên/điện thoại/địa chỉ, lọc trạng thái, 30 đơn/trang; mở chi tiết và nhật ký của đơn cũ. Màn hình lập chuyến/đơn chính vẫn ưu tiên tối đa 1.000 đơn mới, không phải trang lưu trữ toàn bộ. Chuyến/phiếu đối soát có nút xem thêm 100 bản ghi cũ.
- **Thông báo trong web:** nút đầu trang hiển thị số chưa đọc, làm mới 30 giây khi trang đang mở, 50 thông báo/trang và đánh dấu trang đã đọc. Dùng nhật ký đơn làm nguồn, phân quyền theo đơn hiện tại; không phải SMS/email/push khi đóng trình duyệt.
- **Phiếu in/QR:** mỗi đơn có nút In phiếu giao / QR. QR được tạo tại máy chủ và chỉ chứa mã đơn; không gửi thông tin người nhận tới dịch vụ tạo QR bên ngoài. Người quét đăng nhập và tra mã theo quyền. Phiếu hiển thị người nhận, hàng hóa, COD, người trả phí và trạng thái thu phí. QR không cấp quyền truy cập.

Hai bảng thêm: `order_settlements`, `notification_reads`; khởi động ứng dụng sẽ tạo bổ sung, không reset dữ liệu. Cài lại requirements để có thư viện `qrcode`. Sau cập nhật, khởi động lại ứng dụng và tải lại trang. Các biên nhận chỉ ghi nhận nghiệp vụ đã xảy ra, không thực hiện giao dịch ngân hàng.


## Chạy trên Render

Xem [RENDER.md](RENDER.md). Repository có Dockerfile cài Microsoft ODBC 18, Gunicorn và render.yaml. Cần SQL Server/Azure SQL có thể kết nối từ Render; database cục bộ Windows không tự được chuyển lên cloud.
