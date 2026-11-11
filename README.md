# Network Backup System — Project khung TV1

> **Da co project khung TV1 va service TV3.** TV3 da co Inventory CRUD, ket noi dong thoi, Collector va xuat JSON/CSV; da kiem thu bang thiet bi mo phong. Main CLI chua tich hop service TV3 va chua ket noi GNS3. BackupScheduler, RestoreManager va cau hinh hang loat do TV4-TV5 phat trien.

## Yeu cau

- Windows 11, VS Code, Git
- Python 3.10 tro len (khuyen nghi 3.11)

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
- TV3: services/inventory.py, services/connection_manager.py, services/collector.py
- TV4: services/backup.py, version_manager.py, config_diff.py, scheduler
- TV5: services/restore.py, config_manager.py, verification.py, templates/

Xem `docs/API_CONTRACTS.md` va `docs/HUONG_DAN_TV1.md`.

Chi tiet chuc nang va kiem thu TV3: [TV3/README.md](TV3/README.md).

## Luu y

- IP `192.0.2.x` la dia chi de minh hoa, khong phai IP router that.
- `FakeDevice` khong co SSH, khong thuc hien cau hinh tren router.
- `--self-test` chi la smoke test, khong thay the test module va kiem thu GNS3.
- KHONG commit `.env`, files backup, log, hoac mat khau len GitHub.
