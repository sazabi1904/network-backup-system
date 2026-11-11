
"""Kiem thu Change Detector tren 4 router trong GNS3."""

import sys
from getpass import getpass

from core.models import DeviceInfo
from devices.ssh_adapter import SSHAdapter
from services.backup_manager import BackupManager
from services.change_detector import ChangeDetector


ROUTERS = {
    "MikroTik-R1": ("192.168.77.11", "mikrotik", "admin"),
    "MikroTik-R2": ("192.168.77.12", "mikrotik", "admin"),
    "FRR-R3": ("192.168.77.13", "frr", "backup"),
    "FRR-R4": ("192.168.77.14", "frr", "backup"),
}


def hien_thi_ket_qua(result):
    """Hien thi ket qua kiem tra thay doi cau hinh."""
    print("\n" + "=" * 55)
    print("         KET QUA CHANGE DETECTOR")
    print("=" * 55)
    print("Thiet bi       :", result.device)

    if not result.success:
        print("Trang thai     : KIEM TRA THAT BAI")
        print("Ly do          :", result.message)
        print("Ma loi         :", result.error_code)
        return

    print("Snapshot goc   :", result.data["snapshot_id"])

    if not result.data["changed"]:
        print("Trang thai     : KHONG CO THAY DOI")
        print("So dong them   : 0")
        print("So dong xoa    : 0")
        print("\nKET LUAN: Cau hinh van giong ban backup.")
        return

    added, removed = [], []

    for line in result.data["diff"].splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])

    print("Trang thai     : PHAT HIEN THAY DOI")
    print("So dong them   :", len(added))
    print("So dong xoa    :", len(removed))

    # Hien thi cac dong cau hinh duoc them va xoa
    for title, symbol, lines in (
        ("CAU HINH DUOC THEM", "+", added),
        ("CAU HINH BI XOA", "-", removed),
    ):
        if lines:
            print(f"\n[{symbol}] {title}:")
            for line in lines:
                print(f"  {symbol} {line}")

    print("\nKET LUAN: Cau hinh da thay doi so voi backup.")


def main():
    """Kiem tra cau hinh router va tra ve exit code."""
    if len(sys.argv) > 2 or (
        len(sys.argv) == 2 and sys.argv[1] not in ROUTERS
    ):
        print("Cach su dung:")
        for router in ROUTERS:
            print(f"  python .\\try_change_real.py {router}")
        return 2

    name = sys.argv[1] if len(sys.argv) == 2 else "MikroTik-R1"
    host, platform, username = ROUTERS[name]

    print("=" * 55)
    print("          TV4 - CHANGE DETECTOR")
    print("=" * 55)

    # Nhap mat khau SSH
    password = getpass(f"Nhap mat khau SSH {name}: ")

    info = DeviceInfo(
        name=name,
        host=host,
        platform=platform,
        port=22,
    )

    device = SSHAdapter(
        info=info,
        username=username,
        password=password,
        frr_shell="linux" if platform == "frr" else "auto",
    )

    detector = ChangeDetector(BackupManager("backups"))

    exit_code = 0

    try:
        print("\n[1] Dang ket noi SSH...")
        device.connect()
        print("Ket noi thanh cong!")

        print("\n[2] Dang so sanh cau hinh...")

        result = detector.check(device)

        hien_thi_ket_qua(result)

        # Kiem tra that bai phai tra exit code 1
        if not result.success:
            exit_code = 1

    except Exception as exc:
        print(
            "\nLOI:",
            type(exc).__name__,
            str(exc),
        )
        exit_code = 1

    finally:
        try:
            device.disconnect()
            print("\nDa dong ket noi SSH.")

        except Exception as exc:
            print(
                "\n[CANH BAO] Loi dong ket noi SSH:",
                type(exc).__name__,
                str(exc),
            )
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
