# TV2 SSH adapter tích hợp với TV1 TV3 TV4
Cập nhật 09/11/2026 theo yêu cầu bàn giao SSH Adapter. Mã chính thức: `devices.ssh_adapter.SSHAdapter`, kế thừa `core.base.NetworkDevice`. Hai entry point `devices.mikrotik.MikroTikDevice` và `devices.frr.FRRDevice` dùng chung triển khai, không sao chép chức năng.

## Cài dependency
Từ thư mục gốc repo, dùng Python 3.10 trở lên:
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r TV2/ssh/requirements.txt
```
Windows: dùng `.venv\Scripts\python.exe` thay `.venv/bin/python`. Netmiko 4.8.0 và Paramiko 5.1.0 là các phiên bản đã kiểm thử. Code adapter chỉ đọc, không tự push/restore; hai phương thức đó raise NotImplementedError theo phạm vi tài liệu yêu cầu.

## Thông tin lab và host key
Theo file bàn giao: MT-R1 192.168.10.21; MT-R2 192.168.10.22; FRR-1 192.168.10.25. Đây khác subnet của báo cáo tuần 1. Phải kiểm tra đường mạng từ máy chạy Python tới cổng SSH 22; cổng Telnet console GNS3 không phải SSH.

Xác minh fingerprint bằng console/quản trị viên đáng tin cậy, rồi SSH thủ công để ghi khóa đã xác minh vào known_hosts:
```bash
ssh backup@192.168.10.21
ssh backup@192.168.10.25
```
Thay backup bằng tài khoản thực tế. Không tự chấp nhận fingerprint chưa đối chiếu; adapter bật ssh_strict, đọc system known_hosts. Có thể truyền `known_hosts="/path/to/verified_known_hosts"` hoặc CLI `--known-hosts`. Khóa sai/không có trong kho tin cậy gây lỗi; không tự bỏ xác minh. Mật khẩu nhập bằng getpass hoặc biến môi trường, không đưa vào DeviceInfo/Git.

## Dùng trực tiếp với TV4
```python
from getpass import getpass
from core.models import DeviceInfo
from devices.ssh_adapter import SSHAdapter
from services.backup_manager import BackupManager
from services.change_detector import ChangeDetector

info = DeviceInfo("MT-R1", "192.168.10.21", "mikrotik")
manager = BackupManager("backups")
with SSHAdapter(info=info, host=info.host,
                username="backup", password=getpass("SSH password: ")) as device:
    result = manager.backup(device)
    if not result.success:
        raise RuntimeError(result.error_code)
    checked = ChangeDetector(manager).check(device)
    print(result.success, checked.success, checked.data.get("changed"))
```
Đổi info sang `DeviceInfo("FRR-1", "192.168.10.25", "frr")` để dùng FRR. Caller chịu trách nhiệm connect/disconnect khi gọi BackupManager trực tiếp; context manager đảm bảo đóng phiên. BackupScheduler của TV4 tự connect/disconnect, vì vậy truyền danh sách adapter chưa kết nối vào `scheduler.run_once(devices)`.

Không sửa các lớp trong services/. Code TV4 nằm ở nhánh `feature/tv4-backup`, TV3 ở `feature/tv3-inventory`; ví dụ import service chỉ chạy khi code nhánh tương ứng đã có trong checkout tích hợp.

## Dùng qua Factory và ConnectionManager của TV3
```python
from devices.ssh_adapter import register_device_adapters
from core.factory import DeviceFactory

register_device_adapters()
device = DeviceFactory.create(info)
```
Adapter đọc `credentials_from_env(info.credential_ref)` vào thời điểm connect. Với credential_ref là lab cần LAB_USERNAME/LAB_PASSWORD trong môi trường hoặc .env riêng được gitignore. TV3 tiếp tục dùng `ConnectionManager.run(infos, operation=manager.backup)` sau đăng ký Factory. Mỗi đối tượng sở hữu phiên riêng; không chia sẻ cùng một instance giữa nhiều thread.

## Lệnh và xác minh output
| Nền tảng | Probe | Cấu hình |
|---|---|---|
| MikroTik | /system resource print | /export terse |
| FRR Linux shell | vtysh -c "show version" | vtysh -c "show running-config" |

FRR mặc định auto: thử vtysh từ Linux shell; chỉ khi CLI trả lỗi dạng % Unknown command mới thử lệnh trực tiếp. Có thể chọn frr_shell="linux" hoặc "vtysh" rõ ràng. Không tự sudo hoặc thay login shell. Tài khoản cần quyền chạy lệnh đọc FRR.

get_running_config trả str giữ nội dung thiết bị, chuẩn hóa CRLF về LF. FRR phải có dòng frr version và kết thúc bằng end; MikroTik phải có header RouterOS và dòng lệnh export bắt đầu /. Output rỗng, lỗi CLI, cấu hình thiếu phần cuối bị từ chối. Không giả định FRR chỉ có phiên bản 8.2.2 hoặc mọi router đều có eth0; fixture lab kiểm tra 8.2.2 và eth0.

Ngoại lệ dùng chung: DeviceAuthenticationError, DeviceConnectionError, DeviceTimeoutError, DeviceCommandError. Thông báo không chứa raw exception/output/password. Lỗi kết nối/đọc/validate đóng phiên; disconnect gọi lặp an toàn. send_command chỉ cho phép các lệnh đọc trong bảng.

## CLI probe và lấy cấu hình
```bash
.venv/bin/python TV2/ssh/ssh_client.py --platform mikrotik --name MT-R1 --host 192.168.10.21 --username backup
.venv/bin/python TV2/ssh/ssh_client.py --platform frr --name FRR-1 --host 192.168.10.25 --username backup --frr-shell linux
```
CLI hỏi mật khẩu hoặc dùng TV2_SSH_PASSWORD, probe rồi lấy và validate cấu hình. Chỉ in trạng thái và số byte, không in cấu hình có thể chứa bí mật. Exit 0 khi đạt, 1 khi lỗi, 2 khi sai tham số argparse.

Import RouterSSH từ TV2/ssh/ssh_client.py vẫn là alias của adapter nhưng constructor đã đổi sang DeviceInfo; sửa các file try dùng SSH theo mẫu trên. Các báo cáo tuần 1 là ghi nhận lịch sử, không phải trạng thái nghiệm thu hiện tại.

## Kiểm thử đã chạy
11 test đạt ngày 09/11/2026, dùng transport Netmiko mock. Bao gồm Factory/credentials, MikroTik/FRR Linux và vtysh, output bất thường, thiếu end, sai mật khẩu, timeout, sai host key, cleanup và read-only. Test tích hợp chạy nguyên service TV4 tại a4ea441 và TV3 tại 65f06f8, không chỉnh sửa services:
- BackupManager tạo .cfg + .json, SHA-256 nội dung khớp metadata.
- ChangeDetector trả changed=False khi giống baseline và True khi fixture thay đổi.
- BackupScheduler backup hai nền tảng thành công và đóng phiên.
- ConnectionManager tạo adapter từ Factory và kết nối thành công bằng transport mock.

Chạy unit test:
```bash
.venv/bin/python -m unittest discover -s TV2/ssh -p 'test_*.py' -v
```
Hai test service sẽ skip nếu không có checkout nhánh khác. Để chạy đủ:
```bash
git fetch origin
git worktree add --detach ../tv4-check origin/feature/tv4-backup
git worktree add --detach ../tv3-check origin/feature/tv3-inventory
TV2_TV4_ROOT="$PWD/../tv4-check" TV2_TV3_ROOT="$PWD/../tv3-check" .venv/bin/python -m unittest discover -s TV2/ssh -p 'test_*.py' -v
```
PowerShell: đặt hai biến bằng $env:TV2_TV4_ROOT và $env:TV2_TV3_ROOT thành đường dẫn tuyệt đối, rồi chạy lệnh unittest bằng Python trong .venv.

## Chưa nghiệm thu trên router thật
Kiểm tra TCP từ máy thực hiện tới 192.168.10.21:22 chưa thành công. Chưa có kết quả Netmiko thực tế T1–T4 trên MT-R1/MT-R2/FRR-1, backup thực tế T5 hoặc thay đổi cấu hình thật T6. changed=True trong test dùng fixture thay đổi, không gửi lệnh thay đổi router. Cần chạy CLI và ví dụ BackupManager trên máy truy cập được lab với tài khoản/known_hosts hợp lệ; không coi test mock là nghiệm thu SSH thật.

Nguồn API: https://github.com/ktbyers/netmiko . Interface tích hợp: docs/API_CONTRACTS.md của TV1; không có chỉnh sửa các file services/ trong thay đổi này.
