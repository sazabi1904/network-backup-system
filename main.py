"""CLI khung cua TV1. --demo KHONG ket noi router that."""
import argparse
import json
import os
from pathlib import Path
from typing import Dict

from core.base import NetworkDevice
from core.factory import DeviceFactory
from core.models import DeviceInfo
from services.logger import AuditLogger

DEMO_INVENTORY = Path(__file__).parent / "data" / "demo_inventory.json"


def make_demo_devices() -> Dict[str, NetworkDevice]:
    """Thay bang InventoryManager cua TV3 khi tich hop."""
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
    while True:
        print("\n=== NETWORK BACKUP SYSTEM [FAKE DEMO] ===")
        print("1. Danh sach thiet bi mau")
        print("2. Ket noi va doc cau hinh FakeDevice")
        print("3. Thu thay doi va khoi phuc gia lap")
        print("4. Chuc nang se ghep tu TV3-TV5")
        print("0. Thoat")
        choice = input("Nhap lua chon: ").strip()
        if choice == "0":
            print("Tam biet!")
            break
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
            print("TV3: Inventory/Collector; TV4: Backup; TV5: Restore/Deploy - CHUA TICH HOP")
        else:
            print("Lua chon khong hop le")


def main() -> None:
    parser = argparse.ArgumentParser(description="Project khung cua TV1")
    parser.add_argument("--demo", action="store_true", help="Menu dung FakeDevice (khong SSH)")
    parser.add_argument("--self-test", action="store_true", help="Chay thu tu dong 4 FakeDevice")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if run_self_test() else 1)
    if args.demo:
        run_cli()
    else:
        print("Chua tich hop router that. Chay: python main.py --demo")


if __name__ == "__main__":
    main()
