
"""Menu kiem thu cac chuc nang TV4 - Network Backup System."""

import subprocess
import sys
from pathlib import Path

from services.backup_manager import BackupManager


PROJECT_DIR = Path(__file__).resolve().parent

# Danh sach 4 router chinh thuc trong GNS3
ROUTERS = (
    "MikroTik-R1",
    "MikroTik-R2",
    "FRR-R3",
    "FRR-R4",
)

SCRIPTS = {
    "1": "try_backup_real.py",
    "2": "try_change_real.py",
    "3": "try_version_real.py",
    "4": "try_scheduler_real.py",
    "5": "try_report_real.py",
}


def chay_script(filename, *args):
    """Chay file kiem thu bang Python hien tai."""
    path = PROJECT_DIR / filename

    if not path.is_file():
        print(f"\n[LOI] Khong tim thay file: {filename}")
        return

    print(f"\nDang chay: {filename} {' '.join(args)}".rstrip())
    print("-" * 60)

    try:
        result = subprocess.run(
            [sys.executable, str(path), *args],
            cwd=PROJECT_DIR,
            check=False,
        )

        if result.returncode != 0:
            print(
                f"\n[CANH BAO] Chuong trinh tra ve "
                f"ma {result.returncode}."
            )

    except KeyboardInterrupt:
        print("\nDa dung chuc nang dang chay.")

    except OSError as exc:
        print(f"\n[LOI] Khong chay duoc file: {exc}")


def chon_router():
    """Chon mot router hoac ca bon router."""
    print("\nCHON THIET BI")

    for index, name in enumerate(ROUTERS, 1):
        print(f"{index}. {name}")

    print("5. Ca 4 router")
    print("0. Quay lai")

    while True:
        choice = input("Lua chon: ").strip()

        if choice == "0":
            return []

        if choice == "5":
            return list(ROUTERS)

        if choice in ("1", "2", "3", "4"):
            return [ROUTERS[int(choice) - 1]]

        print("Lua chon khong hop le.")


def chay_scheduler():
    """Chon backup mot lan hoac backup dinh ky."""
    print("\nBACKUP SCHEDULER")
    print("1. Backup mot lan")
    print("2. Backup dinh ky")
    print("0. Quay lai")

    mode = input("Lua chon: ").strip()

    if mode not in ("1", "2"):
        if mode != "0":
            print("Lua chon khong hop le.")
        return

    routers = chon_router()

    if not routers:
        return

    # Tu dong kiem tra thay doi truoc khi backup
    args = ["--routers", *routers, "--detect-changes"]

    if mode == "2":
        while True:
            value = input(
                "Chu ky (giay, 0 de huy): "
            ).strip()

            if value == "0":
                return

            if value.isdigit() and int(value) > 0:
                args.extend(("--interval", value))
                break

            print("Nhap so giay nguyen duong.")

        print(
            "Nhan Ctrl+C de dung backup dinh ky "
            "va ve menu."
        )

    chay_script(SCRIPTS["4"], *args)


def chay_diff():
    """So sanh hai snapshot da luu cua cung mot router."""
    print("\nDIFF HAI PHIEN BAN BACKUP")

    names = chon_router()

    if not names:
        return

    if len(names) != 1:
        print("Vui long chon mot router de so sanh.")
        return

    device = names[0]

    # Luon doc dung thu muc backup cua du an
    manager = BackupManager(str(PROJECT_DIR / "backups"))

    try:
        versions = manager.list_snapshots(device)

        if len(versions) < 2:
            print("Can it nhat 2 snapshot de so sanh.")
            return

        print(f"\nDANH SACH PHIEN BAN | {device}")
        print("-" * 75)

        for i, snapshot in enumerate(versions, 1):
            print(
                f"{i:>3}. {snapshot.captured_at} | "
                f"{snapshot.snapshot_id}"
            )

        print("-" * 75)

        old_input = input("Chon STT phien ban CU: ").strip()
        new_input = input("Chon STT phien ban MOI: ").strip()

        if not old_input.isdigit() or not new_input.isdigit():
            print("STT phai la so nguyen duong.")
            return

        old_index = int(old_input) - 1
        new_index = int(new_input) - 1

        if not (
            0 <= old_index < len(versions)
            and 0 <= new_index < len(versions)
        ):
            print("STT phien ban khong hop le.")
            return

        if old_index == new_index:
            print("Hay chon hai phien ban khac nhau.")
            return

        old = versions[old_index]
        new = versions[new_index]

        diff = manager.diff(old, new)

        print("\n" + "=" * 75)
        print("KET QUA SO SANH CAU HINH")
        print("=" * 75)

        print("Router       :", device)
        print("Snapshot cu  :", old.snapshot_id)
        print("Snapshot moi :", new.snapshot_id)

        print("\nDIFF:")
        print(diff if diff else "Hai phien ban giong nhau.")

    except Exception as exc:
        print(
            "[LOI] Khong the so sanh:",
            type(exc).__name__,
            str(exc),
        )


def main():
    while True:
        print("\n" + "=" * 60)
        print(
            "        NETWORK BACKUP SYSTEM - MENU KIEM THU TV4"
        )
        print("=" * 60)

        print("1. Backup Manager   - Sao luu cau hinh")
        print("2. Change Detector  - Phat hien thay doi")
        print("3. Version Manager  - Quan ly phien ban")
        print("4. Backup Scheduler - Sao luu theo lich")
        print("5. Backup Report    - Thong ke, xuat CSV/XLSX")
        print("6. Config Diff      - So sanh 2 phien ban backup")
        print("0. Thoat")

        choice = input("Chon chuc nang: ").strip()

        if choice == "0":
            print("Da thoat menu TV4.")
            return

        if choice in ("1", "2", "3"):
            for name in chon_router():
                chay_script(SCRIPTS[choice], name)

        elif choice == "4":
            chay_scheduler()

        elif choice == "5":
            chay_script(SCRIPTS["5"])

        elif choice == "6":
            chay_diff()

        else:
            print("Lua chon khong hop le.")
            continue

        input("\nNhan Enter de ve menu...")


if __name__ == "__main__":
    try:
        main()

    except (KeyboardInterrupt, EOFError):
        print("\nDa thoat menu TV4.")
