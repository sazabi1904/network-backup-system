# Báo cáo chi tiết nhiệm vụ tuần 1 — TV2

Ngày thực hiện: 31/10/2026. Báo cáo tổng hợp ngày 01/11/2026 từ kết quả phiên cài đặt và các minh chứng đã lưu; không phải một lần chạy kiểm thử mới.

## 1. Mục tiêu và đối chiếu nhiệm vụ

Tuần 1 nhằm tạo môi trường router để các tuần sau phát triển kết nối SSH, đọc cấu hình, áp cấu hình và khôi phục. Kế hoạch ban đầu đề cập Windows RAM 8 GB, GNS3 VM và FRR 10.x. Máy thực tế là Mac M1 RAM 8 GB nên cách triển khai được điều chỉnh.

| Nhiệm vụ | Trạng thái | Kết quả / phần thiếu |
|---|---|---|
| Chuẩn bị GNS3 | Đã thực hiện | Kiểm tra GNS3 2.2.61 đã có sẵn; không cài mới GNS3 |
| Chuẩn bị backend chạy router | Đã thực hiện, còn giới hạn ổn định | Cài QEMU 11.1.3 ARM64 qua Homebrew, dùng TCG để chạy guest x86-64 |
| Chuẩn bị image | Đã thực hiện | CHR 7.23.8 và FRR 8.2.2; FRR chưa phải bản 10.x dự kiến |
| Tạo 4 router | Đã thực hiện | MikroTik-R1/R2 và FRR-R3/R4 đều đã khởi động, vào console |
| Thiết kế topology | Đã làm mạng quản trị | 4 router nối switch MGMT-LAN; chưa có mạng dữ liệu riêng |
| Hostname, IP quản trị | Đã thực hiện | 192.168.77.11–14/24; đã đọc lại cấu hình interface |
| Tài khoản / SSH | Một phần | Đặt mật khẩu MikroTik; quan sát sshd khởi động ở FRR; chưa kiểm tra SSH từ Mac |
| Kiểm tra kết nối nội bộ | Đạt phép thử đã chạy | R1 ping R2/R3/R4: mỗi đích 5/5 gói, mất gói 0% |
| Liên kết dữ liệu và OSPF | Chưa thực hiện | Chưa triển khai hoặc kiểm thử định tuyến động |
| Mốc Python SSH tới ít nhất một router | Chưa đạt | Chưa có thử nghiệm Python/Netmiko kết nối router |

## 2. Kiểm tra môi trường và lựa chọn cách chạy

**Mục đích:** xác định môi trường có thể chạy image router trên kiến trúc Apple Silicon, tránh áp dụng nguyên hướng dẫn dành cho Windows/Intel.

**Đã thực hiện:**

1. Xác nhận máy sử dụng Apple M1, RAM 8 GB.
2. Kiểm tra GNS3 đang chạy phiên bản 2.2.61 và backend local trên macOS.
3. Kiểm tra thư viện thiết bị: ban đầu chỉ có template Cisco C2691.
4. Kiểm tra QEMU đi kèm GNS3: phiên bản 2.10.1, executable x86-64.
5. Ghi nhận máy có Docker và UTM; Docker daemon không chạy tại thời điểm kiểm tra. Không dùng hai ứng dụng này trong lab được bàn giao.
6. Ghi nhận RAM máy sử dụng khoảng 85–86% trong các lần quan sát, do đó bắt đầu với một router rồi mở rộng dần.

**Kết quả:** chọn backend local GNS3 với QEMU, không triển khai GNS3 VM. Đây là lựa chọn đã thử trên máy thực tế, không phải kết luận rằng mọi tổ hợp image/QEMU đều ổn định trên M1.

## 3. Chuẩn bị image MikroTik và FRRouting

### 3.1. MikroTik CHR

- Tải `chr-7.23.8.img.zip` từ máy chủ tải chính thức MikroTik.
- Giải nén `chr-7.23.8.img`, kích thước 134.217.728 byte, vào kho image QEMU của GNS3.
- Tạo template `MikroTik CHR 7.23.8 - M1 test`.
- Cấp mỗi router 1 vCPU, RAM 1024 MB, hai card `virtio-net-pci`, đĩa giao tiếp `virtio`.
- Dùng image x86-64. Trang MikroTik có bản ARM64 tại thời điểm tra cứu, nhưng bản ARM64 không được cài hay kiểm thử trong phiên này.

**Kết quả:** hai CHR đã khởi động, đăng nhập console và hiển thị RouterOS 7.23.8 long-term. Không suy diễn từ việc khởi động được rằng hệ điều hành đã ổn định dài hạn.

### 3.2. FRRouting

- Tra manifest appliance FRR trong kho `GNS3/gns3-registry`.
- Tải `frr-8.2.2.qcow2` từ kho QEMU Appliances của dự án GNS3 trên SourceForge.
- Đối chiếu MD5 với manifest: `45cda6b991a1b9e8205a3a0ecc953640`; kết quả khớp.
- Tạo template `FRR 8.2.2 - M1 lab`.
- Cấp mỗi router 1 vCPU, RAM 256 MB, hai card `e1000`, đĩa giao tiếp `ide`.

**Kết quả:** hai router FRR khởi động được và CLI báo FRRouting 8.2.2. Đây là VM appliance do danh mục GNS3 cung cấp; không mô tả nó là image VM chính thức của dự án FRRouting. Bản 10.x và phương án Docker chưa được triển khai.

## 4. Xử lý backend QEMU

**Sự cố đầu tiên:** GNS3 từ chối khởi động CHR với thông báo thiếu Intel HAXM:

```text
HAXM acceleration support is not installed on this host
(com.intel.kext.intelhaxm extension not loaded)
```

**Đã xử lý:** thêm `-machine accel=tcg` vào tùy chọn router/template để dùng giả lập phần mềm. Việc này áp dụng cho lab, không yêu cầu cài HAXM trên M1.

Sau đó console CHR chưa phản hồi như mong đợi. Đã kiểm tra trạng thái QEMU và thử console VNC để chẩn đoán; VNC không phải phương thức console cuối cùng của lab.

Tiếp tục cài QEMU native ARM64 qua Homebrew và cập nhật template/node sang:

```text
/opt/homebrew/bin/qemu-system-x86_64
-nographic -machine accel=tcg
```

**Kết quả:** QEMU 11.1.3 chạy trên host ARM64 nhưng giả lập guest x86-64. MikroTik hiện màn hình đăng nhập; FRR hiện CLI và dịch vụ định tuyến đã khởi động. Lỗi HAXM đã được xử lý, nhưng lỗi kernel/reboot của RouterOS vẫn được ghi nhận sau khi đổi QEMU; nguyên nhân chưa xác định.

## 5. Dựng topology và mạng quản trị

Tạo project riêng `Network-Backup-M1-Smoke-Test`, thêm bốn router và một Ethernet switch `MGMT-LAN`. Mỗi router dùng card đầu tiên nối vào một cổng riêng của switch.

| Router | Interface trong guest | IP quản trị |
|---|---|---|
| MikroTik-R1 | ether1 | 192.168.77.11/24 |
| MikroTik-R2 | ether1 | 192.168.77.12/24 |
| FRR-R3 | eth0 | 192.168.77.13/24 |
| FRR-R4 | eth0 | 192.168.77.14/24 |

**Mục đích:** tạo cùng một subnet để kiểm tra đường truyền nội bộ giữa hai nền tảng.

**Kết quả:** các IP đã được cấu hình và đọc lại qua console. Interface eth0 trên FRR hiển thị `up`. Các địa chỉ này là IP lab đã dùng, khác địa chỉ minh họa của demo FakeDevice ở repository.

**Giới hạn:** chưa cấu hình Cloud/NAT/bridge hoặc đường định tuyến giúp macOS truy cập subnet này. Ping giữa router không chứng minh Mac có thể SSH vào router. Card thứ hai chưa được dùng để dựng mạng dữ liệu/OSPF.

## 6. Tài khoản và lưu cấu hình

### MikroTik

- Đăng nhập console lần đầu.
- Đặt mật khẩu ngẫu nhiên cho tài khoản quản trị trên hai router; thông tin truy cập chỉ lưu riêng trên máy.
- Đặt hostname và địa chỉ ether1.
- Đọc `/ip address print` và `/system resource print`.
- Gửi lệnh `/export file=baseline` trên cả hai router.

Lệnh export đã được gửi và ghi nhận trong phiên cấu hình. Chưa có kiểm tra độc lập bằng cách tải file baseline về, đối chiếu nội dung hoặc thử restore từ file đó; không tính đây là nghiệm thu backup/restore.

### FRR

- Sử dụng CLI `vtysh` của appliance.
- Đặt hostname trong FRR, cấu hình IP eth0 và `no shutdown`.
- Chạy `write memory`; cả hai router trả thông báo lưu integrated configuration vào `/etc/frr/frr.conf` cùng `[OK]`.
- Đọc `show interface brief` và `show version`.

Hostname FRR được xác nhận ở CLI; chưa có kiểm thử riêng hostname Linux. Dịch vụ sshd đã xuất hiện ở log khởi động FRR, nhưng chưa kiểm thử đăng nhập SSH, chính sách truy cập hoặc đổi tài khoản mặc định của appliance.

## 7. Mô phỏng và kiểm tra kết nối

Từ MikroTik-R1, chạy lần lượt:

```routeros
/ping 192.168.77.12 count=5 interval=200ms
/ping 192.168.77.13 count=5 interval=200ms
/ping 192.168.77.14 count=5 interval=200ms
```

**Kết quả cuối cùng:** mỗi đích gửi 5 gói và nhận 5 gói, mất gói 0%. Tổng cộng 15/15 gói trong ba phép thử. Xem [bảng kết quả và giới hạn phép thử](KET_QUA_KIEM_THU.md).

Lần thử trước đó gặp màn hình đăng nhập thay vì CLI nên lệnh ping không được thực thi đúng. Sau khi đăng nhập lại, ba phép thử mới thành công. Không tính lần nhập lệnh tại màn hình đăng nhập là bằng chứng mất kết nối IP. Các cảnh báo kernel/reboot trên RouterOS được ghi nhận riêng, không quy toàn bộ gián đoạn cho việc hết phiên console.

## 8. Lưu kết quả và dừng lab

- Lưu ảnh topology từ GNS3.
- Lưu kết quả ping có số gói và độ trễ.
- Lưu nhật ký cấu hình trên máy; trong repo chỉ công bố minh chứng đã rà soát theo yêu cầu không commit log nguyên bản của README.
- Lưu hướng dẫn mở project và tài khoản riêng trên máy.
- Dừng bốn QEMU router sau kiểm thử và kiểm tra trạng thái đều là `stopped`, giúp trả lại tài nguyên cho máy RAM 8 GB.

Ảnh topology được chụp khi lab hoạt động, không phải ảnh trạng thái sau khi dừng. Hồ sơ này không bao gồm đĩa VM hay mật khẩu.

## 9. Kết luận nghiệm thu

**Đã đạt:** có mô hình bốn router, hai nền tảng, cấu hình IP quản trị nội bộ và phép thử ping thành công có minh chứng.

**Chưa đạt đầy đủ tuần 1:** còn lỗi ổn định MikroTik, thiếu SSH từ Mac/Python, thiếu mạng dữ liệu và kiểm thử OSPF theo kế hoạch. Chưa triển khai hai adapter Netmiko, chưa tích hợp Factory, Collector, Backup hoặc Restore. Xem [các việc cần hoàn thành](TON_DONG.md).
