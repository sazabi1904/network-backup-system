# Hop dong API (TV1 can chot trong ngay dau)

## 1. Object thiet bi

`DeviceInfo(name, host, platform, port=22, group='lab', role='router', tags=(), credential_ref='lab')`

- `platform`: `mikrotik`, `frr` theo ke hoach; TV2 thong nhat gia tri nay voi TV3.
- Thong tin xac thuc: chi luu `credential_ref` trong Inventory, khong luu password.

## 2. Device interface — `NetworkDevice`

| Ham | Dau vao | Dau ra | Loi |
|---|---|---|---|
| `connect()` | khong | `None` | `DeviceConnectionError`, `DeviceAuthenticationError`, `DeviceTimeoutError` |
| `disconnect()` | khong | `None` | loi phu thuoc adapter |
| `send_command(command)` | `str` | `str` | `DeviceCommandError` |
| `get_running_config()` | khong | `str` | `DeviceCommandError` |
| `push_config(commands)` | `List[str]` | `str` | `DeviceCommandError` |
| `restore_config(backup)` | `str` | `bool` | `DeviceRestoreError` |

Quy uoc: `restore_config` chi tra `True` khi **da xac minh** trang thai sau khoi phuc trong pham vi duoc ho tro. Backup FRR la config dinh tuyen (khong dong nghia toan bo config Linux); backup RouterOS co the chua secrets nen KHONG commit.

## 3. Result va Snapshot

`TaskResult(device, action, success, message, data={}, error_code=None)`

`ConfigSnapshot(snapshot_id, device_name, platform, captured_at, content, sha256, scope)`

TV4/TV5 can thong nhat file luu va pham vi snapshot (`scope`) truoc khi code restore.

## 4. Module service va owner

`core/contracts.py` la Protocol thong nhat. TV3 TV4 TV5 dung cac chu ky trong file nay.

- TV3: `InventoryService.list_devices(group=None, role=None, tag=None) -> List[DeviceInfo]`; `CollectorService.collect(device) -> TaskResult`
- TV4: `BackupService.backup(device) -> TaskResult`; `list_snapshots(device_name) -> List[ConfigSnapshot]`; `diff(left, right) -> str`
- TV5: `RestoreService.restore(device, snapshot) -> TaskResult`; `ConfigService.dry_run/deploy(devices, template_name, variables) -> List[TaskResult]`

Cac service KHONG tu tao netmiko connection ngoai adapter do TV2 cung cap.

## 5. Quy tac audit log

`AuditLogger.log(operator, device, action, success, commands=None, error_code=None)`

- Log luu JSON Lines, moi dong 1 record.
- Lenh nhay cam bi an. Khong truyen exception message co passwords.
- Logging va bao mat phai duoc thuc hien o moi module, khong phai chi TV1.

## 6. Ket noi adapter that (TV2)

Khi xong, TV2 tao `register_device_adapters()` va goi truoc khi khoi tao thiet bi that:

```python
from core.factory import DeviceFactory
from devices.mikrotik import MikroTikDevice
from devices.frr import FRRDevice

DeviceFactory.register("mikrotik", MikroTikDevice)
DeviceFactory.register("frr", FRRDevice)
```

Khong bao gio luu password trong `DeviceInfo`. Adapter lay `credentials_from_env(info.credential_ref)` tai thoi diem connect.

## 7. Tinh huong kiem thu chung

1. FakeDevice tra config va restore ban dau.
2. Gia lap offline, apply fail, restore fail.
3. Backup manager dung get_running_config, khong SSH truc tiep.
4. Restore manager nhan ConfigSnapshot va validate platform/scope truoc khi restore.
5. Config manager dry-run KHONG goi push_config.
6. Truoc khi thay doi that: backup, validate, xac nhan, deploy, verify, rollback neu can.
