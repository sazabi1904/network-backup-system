
"""Kiem thu 9 dieu kien Version Manager cho tung router."""

import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.backup_manager import BackupManager
from services.version_manager import VersionManager

ROUTERS = ("MikroTik-R1", "MikroTik-R2", "FRR-R3", "FRR-R4")
BACKUP_DIR = Path("backups")
VN_TZ = timezone(timedelta(hours=7))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def to_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    check(dt.tzinfo is not None, "Thoi gian thieu mui gio")
    return dt.astimezone(timezone.utc)


def read_disk(device):
    """Doc .json/.cfg truc tiep, doi chieu doc lap voi VersionManager."""
    data = {}

    for path in BACKUP_DIR.glob(f"{device}_*.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        sid = meta["snapshot_id"]
        cfg = BACKUP_DIR / f"{sid}.cfg"
        raw = cfg.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()

        check(path.stem == sid, "Ten file JSON khong khop ID")
        check(meta["device_name"] == device, "Sai ten router")
        check(sid not in data, "Snapshot ID bi trung")
        check(
            meta.get("content_file", cfg.name) == cfg.name,
            "Ten file CFG khong khop"
        )
        check(sha == meta["sha256"], f"Sai SHA-256: {sid}")

        data[sid] = {
            "time": to_utc(meta["captured_at"]),
            "content": raw.decode("utf-8"),
            "sha": sha,
            "platform": meta["platform"],
            "cfg": cfg,
            "json": path,
        }

    check(len(data) >= 2, f"Can it nhat 2 ban backup {device}")
    check(
        {p.stem for p in BACKUP_DIR.glob(f"{device}_*.cfg")} == set(data),
        "File CFG va JSON khong khop nhau"
    )

    return data


def show_versions(device, versions):
    print(f"\nVERSION MANAGER | {device}")
    print(f"Tong so phien ban: {len(versions)}")
    print("-" * 68)
    print(
        f"{'STT':<5}{'THOI GIAN GMT+7':<22}"
        f"{'MA RUT GON':<15}{'SO DONG':<10}GHI CHU"
    )

    # Chuyen doi thoi gian mot lan
    times = [to_utc(v.captured_at) for v in versions]
    newest = max(times, default=None)

    for i, (version, when) in enumerate(zip(versions, times), 1):
        local = when.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")
        note = "Moi nhat" if when == newest else ""

        print(
            f"{i:<5}{local:<22}{version.snapshot_id[-8:]:<15}"
            f"{len(version.content.splitlines()):<10}{note}"
        )

    print("-" * 68)


def main(device):
    vm = VersionManager(BackupManager(str(BACKUP_DIR)))

    try:
        versions, list_error = vm.list_versions(device), None
    except Exception as exc:
        versions, list_error = [], exc

    try:
        disk, disk_error = read_disk(device), None
    except Exception as exc:
        disk, disk_error = {}, exc

    # PHAN 1: HIEN THI PHIEN BAN
    if list_error:
        print(f"Khong doc duoc phien ban: {list_error}")
    else:
        try:
            show_versions(device, versions)
        except Exception as exc:
            print(f"Loi hien thi: {exc}")

    # PHAN 2: KIEM THU
    def test_files():
        check(disk_error is None, str(disk_error))

    def ready():
        test_files()
        check(list_error is None, str(list_error))

    def test_list():
        ready()
        ids = [v.snapshot_id for v in versions]

        check(len(ids) == len(set(ids)), "Snapshot ID bi trung")
        check(set(ids) == set(disk), "Danh sach thieu/thua snapshot")

    def test_order():
        ready()
        times = [to_utc(v.captured_at) for v in versions]

        check(times == sorted(times, reverse=True), "Sai thu tu")

        for v in versions:
            check(v.snapshot_id in disk, "ID khong co tren dia")
            check(
                to_utc(v.captured_at) == disk[v.snapshot_id]["time"],
                "Thoi gian khong khop metadata"
            )

    def test_latest():
        test_files()
        latest = vm.latest_version(device)

        check(latest is not None, "Khong co ban moi nhat")
        check(latest.snapshot_id in disk, "ID moi nhat khong hop le")
        check(
            disk[latest.snapshot_id]["time"]
            == max(item["time"] for item in disk.values()),
            "Chon sai ban moi nhat"
        )

    def test_get_all():
        test_files()

        for sid, original in disk.items():
            v = vm.get_version(device, sid)

            check(v.snapshot_id == sid, "Sai Snapshot ID")
            check(v.device_name == device, "Sai router")
            check(v.content == original["content"], "Sai noi dung CFG")
            check(v.sha256 == original["sha"], "Sai SHA-256")
            check(v.platform == original["platform"], "Sai platform")
            check(
                to_utc(v.captured_at) == original["time"],
                "Sai thoi gian"
            )

    def expect_value_error(name, sid):
        try:
            vm.get_version(name, sid)
        except ValueError:
            return

        raise AssertionError("Khong phat sinh ValueError")

    def test_invalid_id():
        expect_value_error(
            device, "INVALID_" + uuid.uuid4().hex
        )

    def test_unknown_device():
        unknown = "UNKNOWN_" + uuid.uuid4().hex

        check(vm.list_versions(unknown) == [], "Router la co snapshot")
        check(
            vm.latest_version(unknown) is None,
            "Router la co latest"
        )
        expect_value_error(unknown, "INVALID")

    def test_isolation():
        test_files()

        other = next(name for name in ROUTERS if name != device)
        expect_value_error(other, next(iter(disk)))

    def test_corruption():
        test_files()
        sid, item = next(iter(disk.items()))

        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)

            # Sao chep hai file vao thu muc tam
            for ext in ("cfg", "json"):
                shutil.copy2(item[ext], temp / f"{sid}.{ext}")

            # Chi pha hong ban sao, khong sua file backup goc
            with (temp / f"{sid}.cfg").open("ab") as f:
                f.write(b"\nCORRUPTION_TEST\n")

            try:
                found = BackupManager(str(temp)).list_snapshots(device)

            except ValueError as exc:
                check(
                    any(
                        word in str(exc).lower()
                        for word in ("corrupt", "sha", "hash")
                    ),
                    "Loi khong lien quan den file bi hong"
                )
            else:
                check(
                    all(v.snapshot_id != sid for v in found),
                    "Van chap nhan file backup bi hong"
                )

    tests = [
        ("File CFG/JSON va SHA-256", test_files),
        ("Liet ke day du phien ban", test_list),
        ("Sap xep dung thoi gian", test_order),
        ("Xac dinh ban moi nhat", test_latest),
        ("Truy xuat tat ca snapshot", test_get_all),
        ("Xu ly Snapshot ID sai", test_invalid_id),
        ("Xu ly router khong ton tai", test_unknown_device),
        ("Khong nham snapshot giua router", test_isolation),
        ("Phat hien file backup bi hong", test_corruption),
    ]

    print("\nKET QUA KIEM THU")
    passed = 0

    for label, func in tests:
        try:
            func()
            passed += 1
            print(f"[PASS] {label}")
        except Exception as exc:
            print(f"[FAIL] {label} - {exc}")

    print("-" * 68)
    print(f"TONG KET: {passed}/{len(tests)} PASS")

    if passed != len(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) > 2 or (
        len(sys.argv) == 2 and sys.argv[1] not in ROUTERS
    ):
        print(
            "Cach dung: python .\\try_version_real.py "
            "[MikroTik-R1|MikroTik-R2|FRR-R3|FRR-R4]"
        )
        raise SystemExit(2)

    main(sys.argv[1] if len(sys.argv) == 2 else "MikroTik-R1")
