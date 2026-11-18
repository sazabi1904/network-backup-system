# Network Backup System — Project khung TV1

> **TV2–TV5:** đã bổ sung adapter ghi opt-in, strict restore và OSPFv2 backbone. Xem [phạm vi, cách chạy và kết quả nghiệm thu SSH thật](TV2/OSPF_TV2_TV5.md). Adapter mặc định vẫn chỉ đọc.

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

## Chay luong TV2 va TV3

Chuan bi Inventory voi IP router, thong tin dang nhap trong moi truong va host key da xac minh theo [huong dan ghep TV2-TV3](TV2/GHEP_TV2_TV3.md).

```powershell
.\.venv\Scripts\python.exe main.py --check-connections --inventory data/inventory.yaml
.\.venv\Scripts\python.exe main.py --collect --inventory data/inventory.yaml --output-dir reports/tv2-tv3
```

File `data/inventory.yaml` chua IP minh hoa. Cap nhat ban Inventory cuc bo truoc khi chay SSH. Dung `--group`, `--role`, `--tag` de loc thiet bi, `--workers` va `--timeout` de dieu chinh ket noi.

## Luu y

- IP `192.0.2.x` la dia chi de minh hoa, khong phai IP router that.
- `FakeDevice` khong co SSH, khong thuc hien cau hinh tren router.
- `--self-test` chi la smoke test, khong thay the test module va kiem thu GNS3.
- KHONG commit `.env`, files backup, log, hoac mat khau len GitHub.
