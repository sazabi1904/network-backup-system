"""CLI cho demo TV1 va luong Inventory/SSH/Collector cua TV2-TV3."""
import argparse
import json
import math
import os
import sys
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
    while True:
        print("\n=== NETWORK BACKUP SYSTEM [FAKE DEMO] ===")
        print("1. Danh sach thiet bi mau")
        print("2. Ket noi va doc cau hinh FakeDevice")
        print("3. Thu thay doi va khoi phuc gia lap")
        print("4. Huong dan chay Inventory va SSH")
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
    # Giu nguyen cac lenh CLI cu de khong pha bo test/automation cua TV1-TV3.
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        run_full_menu()
        return

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
    if args.demo:
        run_cli()
    else:
        parser.print_help()




# ================================================================
# MENU TICH HOP TV1 - TV5
# Giu nguyen --self-test/--demo/--collect/--check-connections cua TV1.
# ================================================================
PROJECT_DIR = Path(__file__).resolve().parent
LAB_INVENTORY = PROJECT_DIR / "data" / "inventory.yaml"


def _pause():
    input("\nNhan Enter de tiep tuc...")


def _read_choice(prompt, valid):
    while True:
        choice = input(prompt).strip()
        if choice in valid:
            return choice
        print("Lua chon khong hop le.")


def _load_lab_inventory():
    from services.inventory import InventoryManager

    manager = InventoryManager(LAB_INVENTORY)
    return manager, manager.load()


def _select_infos(infos, *, allow_all=True):
    """Chon thiet bi tu Inventory (khong khai bao lai dia chi IP)."""
    if not infos:
        print("Inventory dang rong.")
        return []
    print("\n--- CHON THIET BI ---")
    for i, info in enumerate(infos, 1):
        print(f"{i}. {info.name} | {info.host} | {info.platform}")
    all_choice = str(len(infos) + 1)
    if allow_all:
        print(f"{all_choice}. Tat ca thiet bi")
    print("0. Quay lai")
    valid = {str(i) for i in range(1, len(infos) + 1)} | {"0"}
    if allow_all:
        valid.add(all_choice)
    selected = _read_choice("Lua chon: ", valid)
    if selected == "0":
        return []
    if allow_all and selected == all_choice:
        return infos
    return [infos[int(selected) - 1]]


def _print_inventory(infos):
    if not infos:
        print("Khong co thiet bi phu hop.")
    for info in infos:
        print(
            f"{info.name:14} {info.host:16} {info.platform:9} "
            f"port={info.port} group={info.group} role={info.role} "
            f"tags={','.join(info.tags) or '-'}"
        )


def _inventory_menu():
    """Inventory cua TV3: xem/loc va them/sua/xoa qua API goc."""
    from core.models import DeviceInfo

    while True:
        print("\n=== TV3 - INVENTORY ===")
        print("1. Xem toan bo danh sach")
        print("2. Loc theo group / role / tag")
        print("3. Them thiet bi")
        print("4. Sua thong tin thiet bi")
        print("5. Xoa thiet bi")
        print("0. Quay lai")
        choice = _read_choice("Chon: ", set("012345"))
        if choice == "0":
            return
        try:
            manager, infos = _load_lab_inventory()
            if choice == "1":
                _print_inventory(infos)
            elif choice == "2":
                group = input("Group (Enter: bo qua): ").strip() or None
                role = input("Role (Enter: bo qua): ").strip() or None
                tag = input("Tag (Enter: bo qua): ").strip() or None
                _print_inventory(manager.list_devices(group=group, role=role, tag=tag))
            elif choice == "3":
                name = input("Ten thiet bi: ").strip()
                host = input("IP thiet bi: ").strip()
                platform = input("Platform (mikrotik/frr): ").strip().lower()
                port = input("Port [22]: ").strip() or "22"
                group = input("Group [lab]: ").strip() or "lab"
                role = input("Role [router]: ").strip() or "router"
                tags = input("Tags (phan cach boi dau phay): ").strip()
                credential_ref = input("Credential ref [lab]: ").strip() or "lab"
                if platform not in {"mikrotik", "frr"}:
                    print("Platform ho tro: mikrotik hoac frr")
                    continue
                added = DeviceInfo(
                    name=name, host=host, platform=platform, port=int(port),
                    group=group, role=role,
                    tags=tuple(t.strip() for t in tags.split(",") if t.strip()),
                    credential_ref=credential_ref,
                )
                manager.add_device(added)
                if input("Ghi thay doi vao inventory.yaml? [y/N]: ").strip().lower() == "y":
                    manager.save()
                    print("Đã lưu Inventory.")
                else:
                    print("Đã hủy, không thay đổi file.")
            elif choice == "4":
                selected = _select_infos(infos, allow_all=False)
                if not selected:
                    continue
                info = selected[0]
                name = input(f"Tên mới [{info.name}]: ").strip() or info.name
                host = input(f"IP mới [{info.host}]: ").strip() or info.host
                port = input(f"Port mới [{info.port}]: ").strip() or str(info.port)
                group = input(f"Group mới [{info.group}]: ").strip() or info.group
                role = input(f"Role mới [{info.role}]: ").strip() or info.role
                platform = input(f"Platform mới [{info.platform}]: ").strip().lower() or info.platform
                if platform not in {"mikrotik", "frr"}:
                    print("Platform ho tro: mikrotik hoac frr")
                    continue
                manager.update_device(
                    info.name, name=name, host=host, port=int(port),
                    group=group, role=role, platform=platform,
                )
                if input("Ghi thay doi vao inventory.yaml? [y/N]: ").strip().lower() == "y":
                    manager.save()
                    print("Da luu Inventory.")
                else:
                    print("Da huy, khong thay doi file.")
            elif choice == "5":
                selected = _select_infos(infos, allow_all=False)
                if not selected:
                    continue
                name = selected[0].name
                if input(f"Xac nhan XOA {name} khoi Inventory? Go 'XOA': ").strip() != "XOA":
                    print("Da huy.")
                    continue
                manager.remove_device(name)
                manager.save()
                print("Da xoa khoi file Inventory, khong xoa router GNS3.")
        except (ValueError, KeyError, OSError) as exc:
            print(f"[LOI] Inventory: {type(exc).__name__}: {exc}")
        _pause()


def _connection_collection_menu(collect):
    """TV2/TV3 tren router that; mat khau chi nam tam trong RAM."""
    from dataclasses import replace
    from getpass import getpass
    from devices.ssh_adapter import register_device_adapters
    from services.connection_manager import ConnectionManager
    from services.collector import Collector

    try:
        _, infos = _load_lab_inventory()
        selected = _select_infos(infos)
        if not selected:
            return
        print("\nCần GNS3 và host key SSH đã được xác minh.")
        print("Mật khẩu nhập riêng cho từng router.")
        runtime_infos = []
        previous_env = {}
        try:
            for i, info in enumerate(selected, 1):
                ref = f"TVMENUDEVICE{i}"
                user_key, pass_key = ref + "_USERNAME", ref + "_PASSWORD"
                username_default = "admin" if info.platform == "mikrotik" else "backup"
                username = input(f"Username {info.name} [{username_default}]: ").strip() or username_default
                password = getpass(f"SSH password {info.name}: ")
                previous_env[user_key] = os.environ.get(user_key)
                previous_env[pass_key] = os.environ.get(pass_key)
                os.environ[user_key] = username
                os.environ[pass_key] = password
                runtime_infos.append(replace(info, credential_ref=ref))
            register_device_adapters(frr_shell="linux")
            collector = Collector()
            results = ConnectionManager(max_workers=min(4, len(runtime_infos))).run(
                runtime_infos,
                operation=collector.collect if collect else None,
            )
            for result in results:
                data = result.data if isinstance(result.data, dict) else {}
                print(
                    f"{result.device}: SSH={data.get('connection_status', '-')}, "
                    f"collection={data.get('summary', {}).get('status', '-')}, "
                    f"error={result.error_code or '-'}"
                )
                if collect:
                    for section, detail in data.get("sections", {}).items():
                        print(f"  {section}: {detail.get('status', '-')}")
            if collect:
                dest = PROJECT_DIR / "reports" / "tv2-tv3"
                dest.mkdir(parents=True, exist_ok=True)
                print("JSON:", collector.export_json(results, dest / "collection.json"))
                print("CSV :", collector.export_csv(results, dest / "collection.csv"))
            complete = all(
                r.success and (
                    not collect or r.data.get("summary", {}).get("status") == "success"
                )
                for r in results
            )
            print(f"Ket qua: {'PASS' if complete else 'PARTIAL/FAIL'}")
        finally:
            # Xoa thong tin dang nhap khoi moi truong cua process ke ca khi Ctrl+C.
            for key, previous in previous_env.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous
    except (ValueError, OSError, KeyError) as exc:
        print(f"[LOI] {type(exc).__name__}: {exc}")


def _tv5_live(action, scope='managed'):
    from cli import main as tv5_cli_main
    inventory = input('Inventory lab cục bộ: ').strip()
    name = input('Tên đúng một router: ').strip()
    hosts = input('File known_hosts đã xác minh: ').strip()
    backup_dir = input('Thư mục snapshot (Enter: backups/tv2-write): ').strip() or 'backups/tv2-write'
    args = ['--inventory', inventory, action, '--device', name, '--known-hosts', hosts,
            '--write-scope', scope, '--backup-dir', backup_dir]
    print('Phạm vi: OSPFv2 backbone, cấu hình đang chạy; không ghi IP hoặc startup.' if scope == 'ospf'
          else 'Phạm vi: identity MikroTik hoặc description interface FRR.')
    if action == 'deploy':
        template = 'ospf' if scope == 'ospf' else input('Template tv2_identity hoặc tv2_description: ').strip()
        variables = input('File JSON biến template: ').strip()
        args += ['--template', template, '--vars-file', variables]
        if scope == 'ospf':
            peers = input('Router ID neighbor dự kiến (cách nhau bằng dấu phẩy, Enter: chỉ xác minh cấu hình): ').strip()
            for peer in filter(None, (value.strip() for value in peers.split(','))):
                args += ['--expected-neighbor', peer]
        if tv5_cli_main(args + ['--dry-run']) != 0:
            return
    else:
        args += ['--snapshot-id', input('Snapshot ID đích: ').strip()]
    if input('Nhập GHI để xác nhận thiết bị và phạm vi trên: ').strip() != 'GHI':
        print('Đã hủy, chưa gửi thao tác ghi.')
        return
    print('Kết quả:', tv5_cli_main(args + ['--confirm-write']))


def _tv5_menu():
    """TV5: dry-run / demo an toan; restore/deploy that can adapter ghi."""
    import tempfile
    from core.factory import DeviceFactory
    from services.backup_manager import BackupManager
    from cli import main as tv5_cli_main

    while True:
        print("\n=== TV5 - RESTORE / CONFIG DEPLOY ===")
        print("1. OSPF dry-run (render template, KHONG SSH)")
        print("2. Demo deploy tren FakeDevice (KHONG SSH)")
        print("3. Demo backup -> restore tren FakeDevice (KHONG SSH)")
        print("4. Thong tin ve Restore/Deploy router that")
        print("5. Deploy SSH thật trong phạm vi đã hỗ trợ")
        print("6. Restore SSH thật theo snapshot ID")
        print("7. Deploy OSPFv2 backbone qua SSH thật")
        print("8. Restore OSPF theo snapshot ID")
        print("0. Quay lai")
        choice = _read_choice("Chon: ", set("012345678"))
        if choice == "0":
            return
        if choice == "4":
            print("Adapter mặc định chỉ đọc; mục 5/6 bật WriteSSHAdapter riêng cho tác vụ.")
            print("Identity/description: mục 5/6. OSPFv2 backbone: mục 7/8, scope riêng, không lưu startup FRR.")
            _pause()
            continue
        try:
            if choice in ('5', '6'):
                _tv5_live('deploy' if choice == '5' else 'restore')
                _pause()
                continue
            if choice in ('7', '8'):
                _tv5_live('deploy' if choice == '7' else 'restore', scope='ospf')
                _pause()
                continue
            _, infos = _load_lab_inventory()
            selected = _select_infos(infos, allow_all=(choice != "3"))
            if not selected:
                continue
            if choice in ("1", "2"):
                print("Nhap file JSON bien template, hoac Enter dung vi du OSPF an toan.")
                vars_path = input("Duong dan vars JSON (Enter: vi du): ").strip()
                with tempfile.TemporaryDirectory(prefix="tv5_menu_") as tmp:
                    if not vars_path:
                        vars_file = Path(tmp) / "ospf_vars.json"
                        vars_file.write_text(json.dumps({
                            "router_id": "1.1.1.1",
                            "networks": [{"prefix": "10.0.0.0/24", "area_id": "0.0.0.0"}],
                        }), encoding="utf-8")
                        vars_path = str(vars_file)
                        print("[DEMO] Bien OSPF minh hoa, KHONG dung de deploy router that.")
                    args = [
                        "--inventory", str(LAB_INVENTORY), "deploy",
                        "--template", "ospf", "--vars-file", vars_path,
                    ]
                    for info in selected:
                        args.extend(["--device", info.name])
                    if choice == "1":
                        args.append("--dry-run")
                    else:
                        args.extend(["--demo", "--backup-dir", str(Path(tmp) / "backups")])
                    result = tv5_cli_main(args)
                    print("TV5 return code:", result)
            elif choice == "3":
                info = selected[0]
                with tempfile.TemporaryDirectory(prefix="tv5_restore_demo_") as tmp:
                    backup_dir = Path(tmp) / "backups"
                    fake = DeviceFactory.create(info, demo=True)
                    fake.connect()
                    try:
                        saved = BackupManager(str(backup_dir)).backup(fake)
                    finally:
                        fake.disconnect()
                    if not saved.success:
                        print("[FAIL] Khong tao duoc baseline FakeDevice.")
                    else:
                        args = [
                            "--inventory", str(LAB_INVENTORY), "restore",
                            "--device", info.name, "--demo",
                            "--backup-dir", str(backup_dir),
                        ]
                        print("[DEMO] Restore snapshot tren FakeDevice; khong dung SSH that.")
                        result = tv5_cli_main(args)
                        print("TV5 return code:", result)
        except (ValueError, KeyError, OSError) as exc:
            print(f"[LOI] TV5: {type(exc).__name__}: {exc}")
        _pause()


def _tv1_menu():
    """TV1: kiem tra core va demo OOP."""
    while True:
        print("\n=== TV1 - CORE / DEMO ===")
        print("1. Self-test FakeDevice (Factory + FakeDevice)")
        print("2. Menu demo OOP va AuditLogger")
        print("0. Quay lai")
        choice = _read_choice("Chon: ", set("012"))
        if choice == "0":
            return
        if choice == "1":
            print("[TV1] Ket qua:", "PASS" if run_self_test() else "FAIL")
            _pause()
        else:
            run_cli()


def _tv3_menu():
    """TV3: inventory va collector."""
    while True:
        print("\n=== TV3 - INVENTORY & COLLECTOR ===")
        print("1. Inventory (xem, loc, them, sua, xoa)")
        print("2. Collector: thu thap qua SSH va xuat JSON/CSV")
        print("0. Quay lai")
        choice = _read_choice("Chon: ", set("012"))
        if choice == "0":
            return
        if choice == "1":
            _inventory_menu()
        else:
            _connection_collection_menu(True)
            _pause()


def run_full_menu():
    """Menu chung cua nhom: moi thanh vien mot muc, ben trong chia nho theo chuc nang."""
    while True:
        print("\n" + "=" * 65)
        print("     NETWORK BACKUP SYSTEM - MENU CHUNG TV1 / TV2 / TV3 / TV4 / TV5")
        print("=" * 65)
        print("1. TV1 - Core va demo OOP")
        print("2. TV2 - Kiểm tra kết nối SSH router GNS3")
        print("3. TV3 - Inventory va Collector")
        print("4. TV4 - Backup / Change / Version / Scheduler / Report / Diff")
        print("5. TV5 - Deploy / Restore / OSPF")
        print("0. Thoát")
        choice = _read_choice("Chọn chức năng: ", set("012345"))
        if choice == "0":
            print("Đã thoát chương trình chung.")
            return
        try:
            if choice == "1":
                _tv1_menu()
            elif choice == "2":
                _connection_collection_menu(False)
                _pause()
            elif choice == "3":
                _tv3_menu()
            elif choice == "4":
                # Tich hop nguyen menu TV4 da kiem thu, khong sao chep hoac doi logic.
                from main_TV4 import main as tv4_main
                tv4_main()
            elif choice == "5":
                _tv5_menu()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã dừng thao tác, quay về menu chung.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n Đã thoát chương trình.")
