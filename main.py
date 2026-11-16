"""CLI cho demo TV1 va luong Inventory/SSH/Collector cua TV2-TV3."""
import argparse
import json
import math
import os
from pathlib import Path
from typing import Dict

from core.base import NetworkDevice
from core.factory import DeviceFactory
from core.models import DeviceInfo
from services.logger import AuditLogger

DEMO_INVENTORY = Path(__file__).parent / "data" / "demo_inventory.json"


def make_demo_devices() -> Dict[str, NetworkDevice]:
    """Load the sample devices used by the FakeDevice demo."""
    with DEMO_INVENTORY.open(encoding="utf-8") as fh:
        items = json.load(fh)
    return {
        info.name: DeviceFactory.create(info, demo=True)
        for info in (DeviceInfo.from_mapping(raw) for raw in items)
    }


def run_self_test(logger=None) -> bool:
    """Smoke test nhanh, khong thay the pytest va GNS3."""
    audit = logger or AuditLogger()
    devices = make_demo_devices()
    print("[DEMO] 4 FakeDevice (khong dung SSH that)")
    for name, device in devices.items():
        device.connect()
        config_before = device.get_running_config()
        device.push_config(["! simulated-test-only"])
        is_restored = device.restore_config(config_before)
        verified = is_restored and device.get_running_config() == config_before
        audit.log(os.getenv("APP_OPERATOR", "local_demo"), name,
                  "fake_push_and_restore", verified,
                  commands=["! simulated-test-only"])
        device.disconnect()
        print(f"  {name}: {'PASS' if verified else 'FAIL'}")
        if not verified:
            return False
    return True


def run_cli() -> None:
    """CLI cho phan loi; menu day du se goi cac service cua TV3-TV5."""
    devices = make_demo_devices()
    audit = AuditLogger()
    operator = os.getenv("APP_OPERATOR", "local_demo")
    print("\n=== NETWORK BACKUP SYSTEM [FAKE DEMO] ===")
    print("1. Danh sach thiet bi mau")
    print("2. Ket noi va doc cau hinh FakeDevice")
    print("3. Thu thay doi va khoi phuc gia lap")
    print("4. Huong dan chay Inventory va SSH")
    print("0. Thoat")
    choice = input("Nhap lua chon: ").strip()
    if choice == "0":
        print("Tam biet!")
        return
    if choice == "1":
        for d in devices.values():
            print(f"  {d.info.name}: {d.info.platform} - {d.info.host} (IP gia)")
    elif choice in ("2", "3"):
        device = devices["R1"]
        try:
            device.connect()
            before = device.get_running_config()
            print("Before:", repr(before))
            if choice == "3":
                cmds = ["! simulated-demo-change"]
                device.push_config(cmds)
                print("After:", repr(device.get_running_config()))
                restored = device.restore_config(before)
                print("Restored (FAKE):", restored)
                audit.log(operator, "R1", "fake_restore", restored, cmds)
            else:
                audit.log(operator, "R1", "fake_get_config", True)
        except Exception as exc:
            # Chi log ma loi, khong ghi exception message co the lo secrets
            audit.log(operator, "R1", "fake_demo", False,
                      error_code=type(exc).__name__)
            print("Loi:", type(exc).__name__)
        finally:
            device.disconnect()
    elif choice == "4":
        print("Thu thap SSH: python main.py --collect --inventory <file YAML/JSON>")
    else:
        print("Lua chon khong hop le")


def run_inventory(args) -> int:
    """Run TV3 services with TV2 adapters and export sanitized reports."""
    from devices.ssh_adapter import register_device_adapters
    from services.collector import Collector
    from services.connection_manager import ConnectionManager
    from services.inventory import InventoryManager

    try:
        inventory = InventoryManager(args.inventory)
        inventory.load()
        infos = inventory.list_devices(group=args.group, role=args.role, tag=args.tag)
        if not infos:
            print("Khong co thiet bi phu hop trong Inventory.")
            return 1

        register_device_adapters(
            timeout=args.timeout, known_hosts=args.known_hosts, frr_shell=args.frr_shell,
        )
        collector = Collector()
        operation = collector.collect if args.collect else None
        results = ConnectionManager(max_workers=args.workers).run(infos, operation=operation)
        failed = False
        for result in results:
            status = result.data["connection_status"]
            summary = result.data.get("summary", {}).get("status", "-")
            sections = result.data.get("sections", {})
            errors = [name for name, section in sections.items() if section["status"] == "error"]
            failed = failed or not result.success or bool(errors)
            print(f"{result.device}: SSH={status}, collection={summary}")
            if result.error_code:
                print(f"  error_code={result.error_code}")
            if errors:
                print("  Loi thu thap cac muc: " + ", ".join(errors))
            for key in ("disconnect_error", "logging_error"):
                if key in result.data:
                    print(f"  {key}={result.data[key]}")
                    failed = True

        report_name = "collection" if args.collect else "connections"
        output = Path(args.output_dir)
        json_path = collector.export_json(results, output / f"{report_name}.json")
        csv_path = collector.export_csv(results, output / f"{report_name}.csv")
        print(f"Bao cao JSON: {json_path}")
        print(f"Bao cao CSV: {csv_path}")
        return 1 if failed else 0
    except Exception as exc:
        # Credentials and raw device output can appear in exception messages.
        print(f"Khong hoan thanh tac vu: {type(exc).__name__}")
        return 1


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Network Backup System")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Menu dung FakeDevice (khong SSH)")
    mode.add_argument("--self-test", action="store_true", help="Chay thu tu dong 4 FakeDevice")
    mode.add_argument("--check-connections", action="store_true", help="Kiem tra SSH tu Inventory")
    mode.add_argument("--collect", action="store_true", help="Thu thap MikroTik/FRR qua SSH")
    parser.add_argument("--inventory", help="File Inventory YAML/JSON voi IP router thuc te")
    parser.add_argument("--group", help="Loc theo nhom")
    parser.add_argument("--role", help="Loc theo vai tro")
    parser.add_argument("--tag", help="Loc theo tag")
    parser.add_argument("--workers", type=int, default=4, help="So ket noi dong thoi (mac dinh 4)")
    parser.add_argument("--timeout", type=float, default=30, help="Timeout SSH/lenh, tinh bang giay")
    parser.add_argument("--known-hosts", help="File host key da xac minh; mac dinh dung system known_hosts")
    parser.add_argument("--frr-shell", choices=("auto", "linux", "vtysh"), default="auto")
    parser.add_argument("--output-dir", default="reports/tv2-tv3", help="Thu muc bao cao JSON/CSV")
    args = parser.parse_args(argv)
    if args.workers <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("workers va timeout phai la so duong huu han")
    if args.check_connections or args.collect:
        if not args.inventory:
            parser.error("--check-connections/--collect can --inventory")
        raise SystemExit(run_inventory(args))
    if args.inventory:
        parser.error("--inventory can --check-connections hoac --collect")
    if args.self_test:
        raise SystemExit(0 if run_self_test() else 1)
    # Khong chon che do nao: mo menu FakeDevice (khong SSH, an toan).
    run_cli()


if __name__ == "__main__":
    main()
