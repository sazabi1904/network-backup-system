"""Tong hop bao cao backup 4 router khong can SSH."""

from collections import Counter

from services.backup_manager import BackupManager
from services.backup_report import BackupReport


ROUTERS = ("MikroTik-R1", "MikroTik-R2", "FRR-R3", "FRR-R4")

STATUS = {
    "HAS_BACKUP": "Da sao luu",
    "NO_BACKUP": "Chua sao luu",
    "ERROR": "Loi du lieu",
}


def main():
    report = BackupReport(BackupManager("backups"))
    rows = report.summarize(ROUTERS)
    counts = Counter(row["status"] for row in rows)

    print("\nBACKUP REPORT | 4 ROUTER")
    print("-" * 81)
    print(
        f"{'Router':<15}"
        f"{'So ban':<9}"
        f"{'Thoi gian GMT+7':<22}"
        f"{'Trang thai':<16}"
        "Ma rut gon"
    )

    for row in rows:
        count = row["backup_count"]

        when = (
            f"{row['backup_date']} {row['backup_time']}"
        ).strip() or "-"

        code = (
            row["latest_snapshot_id"][-8:]
            or row["error_code"]
            or "-"
        )

        print(
            f"{row['device']:<15}"
            f"{str(count if count is not None else '-'):<9}"
            f"{when:<22}"
            f"{STATUS[row['status']]:<16}"
            f"{code}"
        )

    print("-" * 81)
    print("Tong thiet bi:", len(rows))

    for status, label in (
        ("HAS_BACKUP", "Da co backup"),
        ("NO_BACKUP", "Chua co backup"),
        ("ERROR", "Loi du lieu"),
    ):
        print(f"{label}: {counts[status]}")

    failures = 0

    for label, export in (
        ("CSV", report.export_csv),
        ("XLSX", report.export_xlsx),
    ):
        try:
            print(f"[PASS] Xuat {label}: {export(ROUTERS)}")

        except Exception as exc:
            failures += 1
            print(
                f"[FAIL] Xuat {label}: "
                f"{type(exc).__name__}: {exc}"
            )

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
