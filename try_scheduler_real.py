
"""Kiem thu BackupScheduler voi 4 router GNS3."""
import os
import argparse
import time
from datetime import datetime, timedelta, timezone
from getpass import getpass
from services.logger import AuditLogger
from core.models import DeviceInfo
from devices.ssh_adapter import SSHAdapter
from services.backup_manager import BackupManager
from services.backup_scheduler import BackupScheduler


ROUTERS = {
    "MikroTik-R1": ("192.168.77.11", "mikrotik", "admin"),
    "MikroTik-R2": ("192.168.77.12", "mikrotik", "admin"),
    "FRR-R3": ("192.168.77.13", "frr", "backup"),
    "FRR-R4": ("192.168.77.14", "frr", "backup"),
}

VN_TZ = timezone(timedelta(hours=7))


def tao_devices(names):
    devices = []

    for name in names:
        ip, platform, username = ROUTERS[name]

        info = DeviceInfo(
            name=name,
            host=ip,
            platform=platform,
            port=22,
        )

        devices.append(
            SSHAdapter(
                info=info,
                host=ip,
                username=username,
                password=getpass(f"Nhap mat khau SSH {name}: "),
                frr_shell="linux" if platform == "frr" else "auto",
            )
        )

    return devices


def hien_thi_ket_qua(results, manager):
    now = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")

    print(f"\nBACKUP SCHEDULER | {now} GMT+7")
    print("-" * 55)

    for result in results:
        status = "PASS" if result.success else "FAIL"
        print(f"[{status}] {result.device}: {result.message}")

        # Hien thi ket qua Change Detector neu duoc bat
        change = (
            result.data.get("change_check")
            if isinstance(result.data, dict)
            else None
        )

        if change:
            print("    Change Detector:", change["status"])

            if change["status"] == "CHANGED":
                print(
                    "    Snapshot goc:",
                    change["baseline_snapshot_id"],
                )

                diff_lines = [
                    line
                    for line in change["diff"].splitlines()
                    if (
                        (
                            line.startswith("+")
                            and not line.startswith("+++")
                        )
                        or (
                            line.startswith("-")
                            and not line.startswith("---")
                        )
                    )
                ]

                print("    So dong thay doi:", len(diff_lines))

        # Neu backup that bai, hien thi ma loi
        if not result.success:
            print("    Ma loi:", result.error_code)
            continue

        # Kiem tra snapshot vua duoc tao
        try:
            snapshots = manager.list_snapshots(result.device)
            print("    Tong so snapshot:", len(snapshots))

            sid = (
                result.data.get("snapshot_id")
                if isinstance(result.data, dict)
                else None
            )

            current = next(
                (s for s in snapshots if s.snapshot_id == sid),
                None,
            )

            if current is None:
                print("    Canh bao: khong tim thay snapshot vua tao")
                continue

            captured_at = datetime.fromisoformat(
                current.captured_at.replace("Z", "+00:00")
            ).astimezone(VN_TZ)

            print("    Snapshot ID:", current.snapshot_id)
            print(
                "    Thoi gian GMT+7:",
                captured_at.strftime("%d/%m/%Y %H:%M:%S"),
            )

        except Exception as exc:
            print(
                "    Loi doc snapshot:",
                type(exc).__name__,
                str(exc),
            )

    print("-" * 55)
    print(
        "TONG KET:",
        f"{sum(r.success for r in results)}/{len(results)}",
        "backup thanh cong",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Kiem thu BackupScheduler TV4"
    )

    parser.add_argument(
        "--routers",
        nargs="+",
        choices=ROUTERS,
        default=list(ROUTERS),
    )

    parser.add_argument(
        "--interval",
        type=int,
        metavar="GIAY",
        help="Chay dinh ky (bo qua de backup mot lan)",
    )

    parser.add_argument(
        "--detect-changes",
        action="store_true",
        help="Tu dong kiem tra thay doi truoc backup",
    )

    args = parser.parse_args()

    if args.interval is not None and args.interval <= 0:
        parser.error("--interval phai lon hon 0")

    devices = tao_devices(dict.fromkeys(args.routers))
    manager = BackupManager("backups")

    scheduler = BackupScheduler(
        manager,
        interval_seconds=args.interval or 300,
        detect_changes=args.detect_changes,
        audit_logger=AuditLogger(),
        operator=os.getenv("APP_OPERATOR", "TV4"),
    )

    # Backup mot lan
    if args.interval is None:
        results = scheduler.run_once(devices)
        hien_thi_ket_qua(results, manager)

        if any(not result.success for result in results):
            raise SystemExit(1)

        return

    # Backup dinh ky
    print(
        f"Backup dinh ky moi {args.interval} giay. "
        "Nhan Ctrl+C de dung."
    )

    try:
        while True:
            results = scheduler.run_pending(devices)

            if results:
                hien_thi_ket_qua(results, manager)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nDa dung backup dinh ky.")


if __name__ == "__main__":
    main()
