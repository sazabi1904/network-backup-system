# Kết quả kiểm thử tuần 1

Nguồn: kết quả console và file tổng hợp được lưu trong phiên lab ngày 31/10/2026. Báo cáo lập ngày 01/11/2026; không chạy lại lab khi biên soạn.

## 1. Phạm vi đã xác nhận

| Mã | Kiểm tra | Minh chứng quan sát | Kết luận |
|---|---|---|---|
| W1-01 | Khởi động CHR R1/R2 | Đăng nhập console được; resource print báo RouterOS 7.23.8 long-term, x86_64, 1024 MiB | Đạt khởi động/CLI; chưa đạt ổn định dài hạn |
| W1-02 | Khởi động FRR R3/R4 | CLI và show version báo FRRouting 8.2.2 | Đạt |
| W1-03 | Địa chỉ R1/R2 | ip address print hiển thị .11/.12 trên ether1 | Đạt tại thời điểm đọc |
| W1-04 | Địa chỉ R3/R4 | show interface brief hiển thị eth0 up, .13/.14 | Đạt tại thời điểm đọc |
| W1-05 | Lưu cấu hình FRR | write memory trả integrated configuration saved to /etc/frr/frr.conf và [OK] | Đạt thao tác lưu |
| W1-06 | Export MikroTik | Đã gửi /export file=baseline trên R1/R2 | Chưa xác minh file độc lập hoặc thử restore |
| W1-07 | Ping R1 → R2 | 5 gửi, 5 nhận, mất gói 0% | Đạt |
| W1-08 | Ping R1 → R3 | 5 gửi, 5 nhận, mất gói 0% | Đạt |
| W1-09 | Ping R1 → R4 | 5 gửi, 5 nhận, mất gói 0% | Đạt |
| W1-10 | Dừng sau kiểm thử | API GNS3 xác nhận bốn QEMU node stopped | Đạt tại cuối phiên |
| W1-11 | SSH từ Mac đến 4 router | Chưa chạy | Chưa kiểm thử |
| W1-12 | Python/Netmiko SSH | Chưa chạy | Chưa kiểm thử |
| W1-13 | OSPF và mạng dữ liệu | Chưa cấu hình | Chưa kiểm thử |

## 2. Bằng chứng phiên bản và IP

Các giá trị dưới đây được trích và trình bày lại từ kết quả console, không phải log vận hành nguyên bản:

| Router | Phiên bản | Interface | Địa chỉ |
|---|---|---|---|
| MikroTik-R1 | RouterOS 7.23.8 (long-term) | ether1 | 192.168.77.11/24 |
| MikroTik-R2 | RouterOS 7.23.8 (long-term) | ether1 | 192.168.77.12/24 |
| FRR-R3 | FRRouting 8.2.2 | eth0, up | 192.168.77.13/24 |
| FRR-R4 | FRRouting 8.2.2 | eth0, up | 192.168.77.14/24 |

## 3. Ping thực tế

Điểm phát: MikroTik-R1. Lệnh mẫu:

```routeros
/ping 192.168.77.12 count=5 interval=200ms
```

Thay địa chỉ đích lần lượt bằng .13 và .14 cho hai phép thử còn lại.

| Đích | Gửi | Nhận | Mất gói | RTT nhỏ nhất | RTT trung bình | RTT lớn nhất |
|---|---:|---:|---:|---:|---:|---:|
| R2 — 192.168.77.12 | 5 | 5 | 0% | 2.075 ms | 10.888 ms | 40.271 ms |
| R3 — 192.168.77.13 | 5 | 5 | 0% | 2.185 ms | 13.525 ms | 54.972 ms |
| R4 — 192.168.77.14 | 5 | 5 | 0% | 3.197 ms | 14.522 ms | 42.104 ms |

[JSON kết quả đã tổng hợp](ping-summary.json). RTT lấy theo thống kê do RouterOS trả về, không tự tính lại từ số hiển thị đã làm tròn.

Lần thử trước gặp màn hình Login/Password; lệnh ping bị hiểu thành thông tin đăng nhập nên không tạo kết quả ICMP hợp lệ. Sau đăng nhập lại mới có ba kết quả đạt nêu trên.

## 4. Giới hạn diễn giải

- Ba phép thử xác nhận liên lạc nội bộ từ R1 tới từng router còn lại tại một thời điểm; chưa phải kiểm thử đầy đủ mọi cặp nguồn/đích.
- ICMP trả lời có đường hồi đáp, nhưng chưa có các lượt ping riêng do R2/R3/R4 chủ động phát.
- Không chứng minh kết nối SSH/TCP 22, quyền thực thi lệnh, tương thích Netmiko hoặc khả năng truy cập subnet từ macOS.
- Không có kiểm thử tải, chạy liên tục, OSPF, khôi phục cấu hình hay mất kết nối có chủ đích.
- Log RouterOS ghi nhận kernel failure, service malfunction và reboot. Ping đạt không đủ để kết luận lab ổn định.
- Cảnh báo reboot xuất hiện trong quá trình có thao tác stop/start để chẩn đoán; chưa phân loại được nguyên nhân của từng lần reboot. Cảnh báo kernel failure/service malfunction vẫn là vấn đề cần xử lý.
- Thời gian trong guest chưa được xác minh đồng bộ với host; không dùng timestamp guest để suy ra thời lượng ổn định.

## 5. Kết luận

Đạt mô phỏng kết nối IPv4 cơ bản trong mạng quản trị. Chưa đủ điều kiện nghiệm thu đầy đủ tuần 1 hoặc chuyển lab sang sử dụng ổn định cho tích hợp backup/restore. Các điều kiện còn thiếu nằm trong [TON_DONG.md](TON_DONG.md).
