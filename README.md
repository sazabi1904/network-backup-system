# Network Backup System — Project khung TV1

> **Chi la project khung + demo FakeDevice.** Chua ket noi GNS3, chua co Inventory CRUD, BackupScheduler, RestoreManager hay Cấu hình hàng loạt that. Cac module do do TV2-TV5 phat trien.

## Yeu cau

- Windows 11, VS Code, Git
- Python 3.9 tro len (khuyen nghi 3.11)

## Chay tren Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --self-test
.\.venv\Scripts\python.exe main.py --demo
.\.venv\Scripts\python.exe -m pytest -q
```

Neu muon dung `python` thay vi duong dan `.venv\Scripts\python.exe`, kich hoat PowerShell ` .\.venv\Scripts\Activate.ps1` (tuy chinh sach thuc thi) hoac chon interpreter .venv trong VS Code.

## Phan cong

- TV1: core/*, main.py, services/logger.py; on dinh API, logging, security, tich hop
- TV2: devices/mikrotik.py, devices/frr.py + GNS3; dang ky adapter voi Factory
- TV3: services/inventory.py, connection.py, collector.py
- TV4: services/backup.py, version_manager.py, config_diff.py, scheduler
- TV5: services/restore.py, config_manager.py, verification.py, templates/

Xem `docs/API_CONTRACTS.md` va `docs/HUONG_DAN_TV1.md`.

## Luu y

- IP `192.0.2.x` la dia chi de minh hoa, khong phai IP router that.
- `FakeDevice` khong co SSH, khong thuc hien cau hinh tren router.
- `--self-test` chi la smoke test, khong thay the test module va kiem thu GNS3.
- KHONG commit `.env`, files backup, log, hoac mat khau len GitHub.
