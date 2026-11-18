# TV2: đọc RouterOS export khi SSH timeout gián đoạn

Nhánh sửa bắt đầu từ `main` tại `e5b5d64` (PR #13). Lỗi được báo: SSH kết nối được nhưng Backup đọc `/export terse` thất bại sau khoảng 30,6 giây. Chưa xác định nguyên nhân gốc của lần lỗi đó là prompt, tải RouterOS hay truyền dữ liệu; bài A/B ở vòng kiểm thử này không tái hiện được timeout tự nhiên.

## Thay đổi

- Riêng `/export terse` dùng prompt root hiện tại đã xác nhận, escape đầy đủ và anchor tới cuối output. Tắt bước tự tìm prompt lần nữa trong `send_command`, giữ `cmd_verify=True` để không thay hành vi kiểm tra echo toàn cục.
- Giữ prompt trong output cho tới khi kiểm tra hoàn tất, rồi mới loại prompt. Chặn `#error exporting ...`, output thiếu terminator/header hoặc lỗi thiết bị. Không công bố backup thành công từ dữ liệu dở.
- Khi đọc timeout hoặc mất transport: đóng phiên, kết nối mới với cùng strict host key/credentials, refresh prompt và thử lại đúng lệnh đọc tối đa một lần. Có thể tắt retry bằng `export_retries=0`.
- Không retry lệnh ghi, không chạy lại toàn bộ Deploy/Restore. Giữ cơ chế rollback của TV5 và điều kiện backup dự phòng trước restore.
- Metadata an toàn trong `device.export_diagnostics` và exception: pha (`prompt_refresh`, `command_echo`, `output_prompt`, `export_read`, `export_validation`, `reconnect`), mã lỗi, số lần thử, thời gian, timeout và số byte nếu biết. Không log prompt, raw exception, config hoặc credentials.
- Pattern dùng cờ regex theo scoped group để tương thích việc Netmiko bọc pattern bằng capturing group trên Python 3.13. Có test chạy qua `read_until_pattern` thật của Netmiko để kiểm tra trường hợp này.

API NetworkDevice và các lớp exception chung được giữ. Không sửa các service TV3/TV4/TV5. `cli.py` chỉ nối tham số export tới Factory, còn các entry point/runner TV2 nhận cùng tham số.

## Timeout và retry

`SSHAdapter(..., timeout=30, export_read_timeout=None, export_retries=1)` và `register_device_adapters(...)` nhận tham số mới. Nếu không chỉ định, timeout export kế thừa `timeout` cũ, mặc định 30 giây. Không tăng mặc định lên 120 giây để che lỗi chưa rõ nguyên nhân.

Netmiko 4.8.0 vẫn có ngân sách chờ echo riêng 10 giây; `export_read_timeout` điều khiển bước đọc output/prompt, không bảo đảm tăng thời hạn echo. Pha lỗi được phân loại để phân biệt hai trường hợp.

```sh
python cli.py --inventory inventory.local.yaml deploy --device MikroTik-R1 --template ospf --vars-file ospf-r1.json --write-scope ospf --known-hosts known_hosts.lab --export-read-timeout 60 --export-retries 1 --dry-run
python cli.py --inventory inventory.local.yaml restore --device MikroTik-R1 --snapshot-id SNAPSHOT_ID --write-scope ospf --known-hosts known_hosts.lab --export-read-timeout 60 --export-retries 1 --confirm-write
```

Ví dụ dùng 60 giây để cấu hình tường minh; đây không phải giá trị mặc định bắt buộc. Tùy chọn `--export-read-timeout` cũng có trong `python -m TV2.ssh.ssh_client` và các runner dưới đây.

Runner OSPF dùng `--convergence-timeout 90` để chờ hội tụ; `--timeout` cũ vẫn là alias cho timeout hội tụ. Timeout export được truyền riêng, tránh nhầm hai thời hạn.

## Kiểm thử

```sh
python -m pytest -q
python -m TV2.ssh.export_acceptance --inventory inventory.local.yaml --device MikroTik-R1 --device MikroTik-R2 --known-hosts known_hosts.lab --iterations 20 --export-read-timeout 30
python -m TV2.ssh.ospf_acceptance --inventory inventory.local.yaml --plan ospf-plan.json --known-hosts known_hosts.lab --convergence-timeout 90 --export-read-timeout 30 --confirm-write
```

Runner export chỉ đọc: kiểm tra nhiều lần trong cùng session, sau đó Backup qua ConnectionManager với session mới; giữ snapshot ở thư mục backups riêng. Báo cáo chỉ chứa hash, timing và metadata đã che dữ liệu nhạy cảm. Dùng inventory/credentials/host keys cục bộ, không đưa lên Git.

Kết quả đã có trước bước hồi quy OSPF:

- **209 pytest PASS**: gồm timeout echo/prompt, refresh lỗi, reconnect bị từ chối xác thực, dừng sau hai lần đọc, export thiếu, không gửi restore/deploy nếu backup lỗi và không replay write timeout.
- A/B trên R1: mặc định **20/20**, explicit pattern **20/20**, cấu hình canonical giống nhau. Median lần lượt 0,760 và 0,688 giây; không coi chênh lệch này là bằng chứng đã xác định nguyên nhân timeout.
- Sau sửa: R1/R2 **40/40** lượt đọc trong session và **40/40** backup qua session mới PASS ở timeout 30 giây, canonical hash ổn định trên từng router.
- Fault injection qua SSH thật trên R1/R2: cố ý ném ReadTimeout sau khi lần đọc thứ nhất hoàn tất, backup phục hồi bằng transport mới. Khi cố ý làm cả hai lần đọc lỗi, Restore dừng với `restore_config` được gọi **0 lần**; cấu hình sau bài thử khớp baseline. Đây là lỗi mô phỏng có chủ đích, không phải tái hiện lỗi gián đoạn tự nhiên 30 giây.

Xem [bằng chứng tổng hợp](evidence/20261118/export-timeout.json) cho kết quả cuối cùng, gồm hồi quy OSPF. Gateway localhost đã được bật lại trong lần kiểm thử vì ban đầu không có listener 2201–2204; lỗi gateway không tính là lỗi export.

## Giới hạn

Prompt hiện hỗ trợ root RouterOS dạng `[user@identity] >`; không nhận submenu hoặc chế độ tương tác khác là export hoàn chỉnh. Hai lần đọc lỗi liên tiếp vẫn trả lỗi, không bỏ điều kiện backup để ghi tiếp. Retry là phục hồi đọc có giới hạn, không bảo đảm router hết chậm và không thay cơ chế console recovery hoặc khóa liên tiến trình.

## Hồi quy OSPF sau sửa

Cả bốn router PASS deploy/idempotence, neighbor, route, tổng 18/18 gói ping, rollback về OSPF đang hoạt động và hội tụ lại. Restore baseline và kiểm tra sau dọn loopback tạm đều exact hash match. Không sửa hay lưu startup FRR.
