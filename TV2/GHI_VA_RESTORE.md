# TV2: ghi cấu hình và tích hợp restore TV5

Bản bổ sung ngày 17/11/2026, dựa trên main `88a9f4e`. Không thay đổi các service TV3/TV4/TV5 hoặc factory mặc định. `SSHAdapter`, `MikroTikDevice`, `FRRDevice` tiếp tục chỉ đọc. Luồng ghi phải chủ động dùng `devices.write_adapter.WriteSSHAdapter`.

## Phạm vi đã triển khai

| Nền tảng | Ghi và khôi phục được | Giới hạn |
| --- | --- | --- |
| MikroTik | `/system identity set name=NAME` | Một tên đơn giản 1–63 ký tự, bắt đầu bằng chữ; không khoảng trắng/ký tự điều khiển. |
| FRR | `interface eth0` → `description TEXT` hoặc `no description` → `exit` | Chỉ interface đã có trong running-config; mô tả 1–80 ký tự chữ/số/khoảng trắng/dấu `_ . -`. Yêu cầu SSH vào Linux shell, có quyền vtysh. |

FRR ghi running-config, không gọi write memory và không sửa startup file. Không hỗ trợ hostname FRR: hostname của vtysh ngắn không chứng minh trạng thái ở phiên tiếp theo. Chưa hỗ trợ restore IP, OSPF, ACL, tạo/xóa interface hoặc toàn bộ thiết bị. Không chạy đồng thời nhiều tác vụ ghi hay chỉnh tay cùng thiết bị trong lúc backup/deploy/restore.

Restore nhận snapshot đầy đủ nhưng **chỉ sửa trường thuộc phạm vi trên**. Nếu IP/interface/cấu hình ngoài phạm vi đã khác snapshot, adapter từ chối trước khi ghi thay vì báo khôi phục một phần là thành công. Trường description ban đầu không tồn tại được khôi phục bằng `no description`.

## Những lỗi TV2 đã xử lý

- Thêm `push_config`, `restore_config`, `validate_config_commands`, `verify_config_commands`, `write_scopes` trong adapter ghi riêng.
- Refresh prompt MikroTik trước đọc export và sau đổi tên; loại bỏ dòng prompt hoàn chỉnh khỏi export, không xóa dòng cấu hình có dấu ngoặc.
- Adapter ghi trả header RouterOS ổn định (`# RouterOS VERSION`) thay timestamp hiện tại. Vì vậy VerificationService gốc của TV5 so hash được mà không phải sửa service. Adapter đọc cũ giữ nguyên timestamp và định dạng đầu ra nếu không có prompt thừa.
- Kiểm tra toàn bộ trạng thái được quản lý và phần cấu hình còn lại sau ghi. Timeout không tự gửi lại lệnh vì có thể lệnh đã áp dụng; TV5 có thể gọi restore để recovery.
- Từ chối lệnh ngoài phạm vi và command injection trước ghi. SSH vẫn kiểm tra host key, không tắt xác minh máy chủ.
- CLI riêng chọn đúng một thiết bị, kiểm tra cú pháp trước kết nối và yêu cầu snapshot ID rõ ràng khi restore; không thay registry toàn cục.

## TV5 sử dụng từ Python

```python
from devices.write_adapter import WriteSSHAdapter
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager

# info là DeviceInfo lấy từ InventoryManager; credentials theo credential_ref.
device = WriteSSHAdapter(info, known_hosts="known_hosts.lab", frr_shell="linux")
backup = BackupManager("backups/tv2-write")
device.validate_config_commands(["/system identity set name=R1-test"])  # MikroTik
with device:
    saved = backup.backup(device)
    if not saved.success:
        raise RuntimeError("Không tạo được baseline")
    baseline = next(s for s in backup.list_snapshots(info.name)
                    if s.snapshot_id == saved.data["snapshot_id"])
    result = ConfigManager(backup_manager=backup).deploy(
        [device], "tv2_identity", {"identity_name": "R1-test"})[0]
    restored = RestoreManager().restore(device, baseline)
    print(result.success, restored.success)
```

Với FRR, preflight các lệnh `['interface eth0', 'description TV2 test', 'exit']`; deploy template `tv2_description` với biến `interface`, `description`.

TV5 gốc chưa gọi tự động `validate_config_commands`/`verify_config_commands`. Khi mở rộng luồng TV5, nên gọi preflight trước backup/ghi và dùng xác minh theo nền tảng. Adapter hiện vẫn tự chặn đầu vào và đọc lại cấu hình; hai template kèm theo cũng tương thích bộ xác minh literal gốc. Lệnh `no description` khi gọi trực tiếp adapter được hỗ trợ, nhưng nếu TV5 dùng kiểm tra literal cho lệnh xóa sẽ cần thay verifier; không có template deploy xóa ở bản này.

**Snapshot:** tạo backup mới bằng cùng WriteSSHAdapter trước khi ghi. Snapshot MikroTik cũ từ adapter đọc có timestamp không tương thích hash của verifier TV5 gốc; CLI từ chối trước ghi. Không tự sửa nội dung/hash backup cũ. TV5 muốn dùng snapshot cũ cần thêm chuẩn hóa so trạng thái, vẫn giữ kiểm tra toàn vẹn nội dung gốc.

## Chạy từ thư mục gốc repository

Credentials theo hợp đồng có sẵn: inventory `credential_ref: mtlab` dùng biến môi trường `MTLAB_USERNAME`, `MTLAB_PASSWORD`; không đưa mật khẩu vào Git. Known-hosts phải chứa khóa đã xác minh. `identity.json` chứa `{"identity_name":"R1-test"}`.

```sh
python -m TV2.ssh.write_cli deploy --inventory inventory.local.yaml --device MikroTik-R1 --known-hosts known_hosts.lab --template tv2_identity --vars-file identity.json --dry-run
python -m TV2.ssh.write_cli backup --inventory inventory.local.yaml --device MikroTik-R1 --known-hosts known_hosts.lab
python -m TV2.ssh.write_cli deploy --inventory inventory.local.yaml --device MikroTik-R1 --known-hosts known_hosts.lab --template tv2_identity --vars-file identity.json
python -m TV2.ssh.write_cli restore --inventory inventory.local.yaml --device MikroTik-R1 --known-hosts known_hosts.lab --snapshot-id ID_TU_KET_QUA_BACKUP
```

FRR dùng `--device FRR-R3 --template tv2_description --vars-file description.json`, trong đó JSON là `{"interface":"eth0","description":"TV2 test"}`. Không bỏ bước backup trước thử nghiệm. CLI deploy cũng tạo backup riêng bằng TV4 trước ghi.

## Bằng chứng kiểm thử

- `python -m pytest -q`: **117 passed** (90 bài có sẵn, 27 bài mới).
- 4/4 router GNS3 qua SSH thật: backup → đổi identity/description → restore → hash cấu hình khớp baseline.
- 4/4 router: cố ý làm verifier thất bại sau ghi thật → TV5 rollback → hash khớp baseline.
- MikroTik R1/R2 và FRR R3/R4 đã trở lại baseline. FRR read-back chạy bằng phiên vtysh mới, không dựa vào biến chỉ tồn tại trong phiên ghi.
- Bằng chứng đã lược bỏ credentials/cấu hình nằm tại `TV2/evidence/write-restore.json` và `TV2/evidence/write-rollback.json`.
- Test tự động có timeout sau khi đã áp dụng, backup thất bại, snapshot sai, drift ngoài phạm vi, command injection, lệnh không hỗ trợ, xóa/khôi phục description và dry-run không kết nối/không đổi factory.

Đây là router ảo chạy RouterOS/FRR trong GNS3, không phải phần cứng vật lý. Chưa kiểm chứng reboot/persistence, mất SSH thực tế sau thay IP, hoặc restore routing. Những mục này cần giai đoạn tiếp theo, không được suy ra từ kết quả identity/description.
