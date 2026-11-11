
"""Kiem thu BackupManager TV4 voi router that trong GNS3."""

import sys
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path

from core.models import DeviceInfo
from devices.ssh_adapter import SSHAdapter
from services.backup_manager import BackupManager


# Danh sach 4 router trong GNS3
ROUTERS = {
    "MikroTik-R1": ("192.168.77.11", "mikrotik", "admin"),
    "MikroTik-R2": ("192.168.77.12", "mikrotik", "admin"),
    "FRR-R3": ("192.168.77.13", "frr", "backup"),
    "FRR-R4": ("192.168.77.14", "frr", "backup"),
}


def main():
    # Chon router can backup
    if len(sys.argv) != 2 or sys.argv[1] not in ROUTERS:
        print("Cach su dung:")
        for name in ROUTERS:
            print(f"  python .\\try_backup_real.py {name}")
        raise SystemExit(2)

    router_name = sys.argv[1]
    router_ip, platform, username = ROUTERS[router_name]

    # 1. Thong tin router
    info = DeviceInfo(
        name=router_name,
        host=router_ip,
        platform=platform,
        port=22,
    )

    # 2. Nhap mat khau
    password = getpass(
        f"Nhap mat khau SSH {router_name}: "
    )

    # 3. Tao SSH Adapter
    device = SSHAdapter(
        info=info,
        username=username,
        password=password,
        frr_shell="linux" if platform == "frr" else "auto",
)

    # 4. Tao BackupManager
    manager = BackupManager(backup_dir="backups")

    try:
        print("\n[1] Dang ket noi SSH...")
        device.connect()
        print("SSH thanh cong!")

        # 5. Goi ham backup that cua TV4
        print("\n[2] Dang backup cau hinh...")
        result = manager.backup(device)

        print("Thiet bi:", result.device)
        print("Trang thai:", result.success)
        print("Thong bao:", result.message)

        if not result.success:
            print("Ma loi:", result.error_code)
            raise SystemExit(1)

        # 6. Lay thong tin snapshot vua tao
        snapshot_id = result.data["snapshot_id"]

        cfg_path = Path("backups") / f"{snapshot_id}.cfg"
        json_path = Path("backups") / f"{snapshot_id}.json"

        print("\n[3] Kiem tra file backup...")
        print("File CFG:", cfg_path)
        print("Ton tai:", cfg_path.is_file())
        print("File JSON:", json_path)
        print("Ton tai:", json_path.is_file())
        if not cfg_path.is_file() or not json_path.is_file():
            raise FileNotFoundError(
                "Thieu file CFG hoac JSON cua snapshot vua tao"
            )

        # 7. Kiem thu list_snapshots va SHA-256
        print("\n[4] Kiem tra danh sach snapshot...")
        snapshots = manager.list_snapshots(info.name)

        print("Tong so snapshot:", len(snapshots))

        current = next(
            s for s in snapshots
            if s.snapshot_id == snapshot_id
        )

        # Chuyen thoi gian backup sang GMT+7
        vietnam_tz = timezone(timedelta(hours=7))

        backup_time = datetime.fromisoformat(
            current.captured_at.replace("Z", "+00:00")
        ).astimezone(vietnam_tz)

        formatted_time = backup_time.strftime(
            "%d/%m/%Y %H:%M:%S"
        )

        print("Snapshot ID:", current.snapshot_id)
        print("Thoi gian GMT+7:", formatted_time)
        print("SHA-256:", current.sha256)
        print("So dong:", len(current.content.splitlines()))

        print("\nBACKUP THANH CONG!")

    except Exception as exc:
        print(
            "\nLOI:",
            type(exc).__name__,
            str(exc),
        )
        raise SystemExit(1)

    finally:
        try:
            device.disconnect()
            print("Da dong ket noi SSH.")
        except Exception as exc:
            print(
                "[CANH BAO] Loi dong ket noi SSH:",
                type(exc).__name__,
                str(exc),
            )


if __name__ == "__main__":
    main()
