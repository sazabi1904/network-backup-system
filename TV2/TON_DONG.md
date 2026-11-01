# Tồn đọng và điều kiện hoàn thành tuần 1

## 1. Các vấn đề đã gặp

| Vấn đề | Hành động đã thực hiện | Trạng thái cuối phiên |
|---|---|---|
| GNS3 yêu cầu Intel HAXM | Đặt -machine accel=tcg cho template/node lab | Đã khởi động được; không cài HAXM |
| QEMU 2.10.1 x86-64 cũ, console CHR khó kiểm tra | Thử console VNC; cài QEMU 11.1.3 ARM64; trở lại Telnet console | Có CLI ở cả hai nền tảng |
| RouterOS báo kernel failure/service malfunction/reboot | Ghi nhận cảnh báo, kiểm tra lại CLI và ping | Chưa xác định nguyên nhân, chưa xử lý dứt điểm |
| Lệnh ping được gửi khi console ở màn hình đăng nhập | Đăng nhập lại, thực hiện lại ba phép thử | Lần thử hợp lệ đạt 5/5 từng đích |
| FRR khác phiên bản dự kiến | Dùng appliance QEMU 8.2.2 trong danh mục GNS3 | Cần nhóm thống nhất phiên bản dùng chính thức |
| Mạng quản trị chưa kết nối với host | Mới nối các router qua switch GNS3 | Chưa SSH từ Mac được kiểm chứng |

Các cảnh báo RouterOS quan sát được gồm “kernel failure in previous boot” và “Automatic supout.rif file generated due to service malfunction”. Đây là triệu chứng, chưa phải kết luận nguyên nhân do RAM, CPU, phiên bản RouterOS hay QEMU.

## 2. Checklist còn lại

- [ ] Xác định và xử lý nguyên nhân kernel/reboot trên MikroTik; ghi rõ phiên bản và tùy chọn của cấu hình thay thế nếu thay đổi.
- [ ] Kiểm thử chạy liên tục, theo dõi uptime, cảnh báo và reboot. Thời lượng nghiệm thu cần thống nhất với nhóm; chưa có kết quả cho mục này.
- [ ] Chốt phiên bản FRR chính thức: giữ 8.2.2 cho lab hiện tại hoặc nâng/dựng lại bản phù hợp kế hoạch 10.x.
- [ ] Thiết lập đường mạng quản trị để macOS truy cập cả bốn IP; ghi lại cơ chế kết nối và bảng địa chỉ thực tế.
- [ ] Kiểm tra tài khoản, dịch vụ SSH và chính sách truy cập của từng nền tảng; chuẩn bị tài khoản lab riêng trước khi mở rộng kết nối.
- [ ] SSH từ Mac đến từng router, chạy lệnh chỉ đọc và lưu minh chứng đã loại bỏ thông tin đăng nhập.
- [ ] Python/Netmiko SSH được ít nhất một router, sau đó cả hai nền tảng.
- [ ] Thiết kế liên kết dữ liệu riêng theo topology nhóm thống nhất; cấu hình và kiểm thử OSPF nếu yêu cầu đề bài.
- [ ] Xác minh cấu hình lưu còn tồn tại sau một lần khởi động lại có kiểm soát; hiện chưa có bộ kiểm thử riêng cho việc này.
- [ ] Hoàn thiện hướng dẫn dựng lại đã được một thành viên khác làm thử.

## 3. Thứ tự ưu tiên đề xuất

1. Xử lý độ ổn định và thống nhất phiên bản image.
2. Hoàn thiện đường quản trị, tài khoản và SSH từ Mac.
3. Thử Python/Netmiko tối thiểu, đối chiếu hợp đồng API TV1.
4. Hoàn thiện topology dữ liệu/OSPF và bằng chứng nghiệm thu.
5. Sang tuần 2: viết adapter tại devices/mikrotik.py và devices/frr.py, đăng ký với Factory theo tài liệu chung.

Đây là kế hoạch công việc tiếp theo, **chưa phải các bước đã hoàn thành**.

## 4. Ranh giới với tuần 2–4

Chưa triển khai MikroTikDevice, FRRDevice hoặc các phương thức connect/disconnect/send_command/get_running_config/push_config/restore_config theo API của project. Chưa kiểm thử cùng TV3–TV5, chưa có unit test adapter, test sai mật khẩu/timeout/offline có chủ đích, backup/version/diff/restore hoặc rollback.

Việc đặt hostname/IP bằng console, gửi lệnh export baseline và ping thành công không thay thế các chức năng đó.
