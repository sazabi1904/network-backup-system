# TV2 — Python kết nối SSH tới router

Module này mở kết nối SSH từ máy chạy Python tới router bằng Netmiko, chạy lệnh đọc thông tin phiên bản và đóng kết nối. Hỗ trợ MikroTik RouterOS và FRR appliance có shell đăng nhập là vtysh. Đây là phần kết nối ban đầu; chưa triển khai adapter NetworkDevice, đăng ký Factory, push_config hoặc restore_config.

## Điều kiện trước khi chạy

- Máy chạy Python phải truy cập được IP và cổng SSH của router. Cổng console Telnet localhost:5001/5004/... của GNS3 không phải cổng SSH.
- Router đang chạy, bật SSH và có tài khoản hợp lệ. Dùng tài khoản riêng của lab.
- Lab tuần 1 mới xác nhận ping giữa router; chưa xác nhận đường SSH từ macOS vào subnet 192.168.77.0/24. Cần bổ sung đường mạng quản trị phù hợp trước khi dùng các IP dưới đây.
- Với FRR, tài khoản SSH phải vào trực tiếp vtysh, có quyền chạy show version. Nếu vào Linux shell, module báo output không đúng; chưa tự chạy sudo hay đổi shell của tài khoản.
- Host key phải được xác minh và lưu trong known_hosts của người chạy Python. Trước tiên chạy SSH thủ công, đối chiếu fingerprint với quản trị viên/console đáng tin cậy rồi mới chấp nhận. Module bật ssh_strict và không tự tin cậy khóa lạ.

## Cài đặt

Từ thư mục gốc repo, trên macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r TV2/ssh/requirements.txt
```

Trên Windows PowerShell dùng py -m venv .venv và thay .venv/bin/python bằng .venv\Scripts\python.exe trong các lệnh tiếp theo.

## Chạy thử

Ví dụ sau dùng IP lab tuần 1; chỉ chạy khi đã thiết lập được đường mạng từ máy tới router:

```bash
ssh admin@192.168.77.11
.venv/bin/python TV2/ssh/ssh_client.py --platform mikrotik --host 192.168.77.11 --username admin
```

Chương trình hỏi mật khẩu bằng getpass, không hiện ký tự trên màn hình. Có thể cấp biến môi trường TV2_SSH_PASSWORD trong môi trường tự động hóa; không commit giá trị mật khẩu và không truyền mật khẩu qua tham số dòng lệnh.

FRR (thay labuser bằng tài khoản thực tế):

```bash
ssh labuser@192.168.77.13
.venv/bin/python TV2/ssh/ssh_client.py --platform frr --host 192.168.77.13 --username labuser
```

Lệnh đọc cố định: MikroTik dùng /system resource print; FRR dùng show version. Thành công khi SSH xác thực, output chứa dấu hiệu phiên bản đúng nền tảng và kết nối được đóng. Exit code 0 là đạt probe; exit code 1 là lỗi kết nối/đọc/kết quả, exit code 2 là sai cú pháp CLI. Có thể đặt --port và --timeout nếu cần.

## Xử lý lỗi

| Thông báo | Việc cần kiểm tra |
|---|---|
| authentication failed | Tài khoản, mật khẩu và quyền SSH |
| timed out | IP, đường mạng từ Mac, cổng SSH, firewall, trạng thái router |
| verified host key | known_hosts và fingerprint đã đối chiếu; không bỏ xác minh để vượt lỗi |
| output in time | Router chậm, tự reboot, timeout hoặc dịch vụ CLI |
| Unexpected CLI output | FRR đang vào Linux shell hoặc CLI trả lỗi; kiểm tra SSH thủ công |

## Kiểm thử và trạng thái nghiệm thu

```bash
.venv/bin/python -m unittest discover -s TV2/ssh -p 'test_*.py' -v
```

Unit test mô phỏng kết nối: sai mật khẩu, timeout mạng, timeout đọc vẫn đóng phiên, CLI FRR không đúng, probe của hai nền tảng và kiểm tra tham số. Chúng không kết nối router thật.

Kết quả ngày 08/11/2026: 6 unit test đạt trên Python 3.13, Netmiko 4.8.0, Paramiko 5.1.0. Đây là kiểm thử offline bằng mock.

Tại lần bổ sung code này chưa có bằng chứng SSH thật từ Mac tới ít nhất một router. Không cập nhật mốc đó thành đạt chỉ dựa trên unit test. Khi chạy thật cần ghi router, phiên bản, ngày thử và output phiên bản đã loại bỏ thông tin nhạy cảm. Cảnh báo kernel/reboot MikroTik từ lab tuần 1 vẫn chưa được xác nhận đã xử lý.

Nguồn API: https://github.com/ktbyers/netmiko — ConnectHandler, tham số ssh_strict/system_host_keys và send_command_timing.
