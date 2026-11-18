"""CLI tich hop TV3 (inventory, thu thap) va TV5 (restore, deploy).

Vi du:
  python cli.py inventory list
  python cli.py collect --demo --out-dir reports
  python cli.py deploy --template ospf --device R1 --vars-file ospf.json --dry-run
  python cli.py restore --device R1 --demo

Dung --demo de chay bang FakeDevice, khong can router that.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from core.factory import DeviceFactory
from core.models import DeviceInfo, TaskResult
from devices.ssh_adapter import register_device_adapters
from services.backup_manager import BackupManager
from services.collector import Collector
from services.config_manager import ConfigManager
from services.connection_manager import ConnectionManager
from services.inventory import InventoryManager
from services.restore import RestoreManager
from core.exceptions import DeviceCommandError

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INVENTORY = PROJECT_DIR / "data" / "inventory.yaml"
DEFAULT_BACKUP_DIR = PROJECT_DIR / "backups"
DEFAULT_TEMPLATE_DIR = PROJECT_DIR / "templates"


def _load_inventory(path: str) -> List[DeviceInfo]:
    return InventoryManager(path).load()


def _select_devices(infos: List[DeviceInfo], names: Optional[Sequence[str]]) -> List[DeviceInfo]:
    """Lay thiet bi theo ten; neu khong truyen --device thi lay tat ca."""
    if not names:
        return infos
    by_name = {info.name: info for info in infos}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise KeyError(f"Khong tim thay thiet bi: {', '.join(missing)}")
    return [by_name[name] for name in names]


def _print_results(results: List[TaskResult]) -> int:
    """In tom tat ket qua; tra ve 0 neu tat ca thanh cong, nguoc lai 1."""
    for result in results:
        status = "OK" if result.success else "LOI"
        code = f" [{result.error_code}]" if result.error_code else ""
        print(f"[{status}] {result.device} - {result.action}: {result.message}{code}")
    return 0 if all(r.success for r in results) else 1


def _run_on_devices(infos: List[DeviceInfo], operation, demo: bool, **options) -> List[TaskResult]:
    previous = dict(DeviceFactory._registry)
    try:
        register_device_adapters(**options)
        manager = ConnectionManager(max_workers=4, demo=demo)
        return manager.run(infos, operation)
    finally:
        DeviceFactory._registry.clear()
        DeviceFactory._registry.update(previous)


def _write_options(args):
    enabled = args.write_scope in ('managed', 'ospf')
    if enabled and not args.demo:
        if not args.device or len(args.device) != 1:
            raise ValueError('Write mode requires exactly one --device')
        if not args.known_hosts:
            raise ValueError('Write mode requires --known-hosts')
        if not getattr(args, 'dry_run', False) and not args.confirm_write:
            raise ValueError('Review dry-run, then pass --confirm-write')
        if args.command == 'restore' and not args.snapshot_id:
            raise ValueError('Real restore requires explicit --snapshot-id')
    return dict(write=enabled and not args.demo, known_hosts=args.known_hosts,
                frr_shell='linux' if enabled else 'auto', write_scope=args.write_scope or 'managed')


# ---------- inventory ----------

def cmd_inventory_list(args) -> int:
    infos = _load_inventory(args.inventory)
    selected = [
        info for info in infos
        if (args.group is None or info.group == args.group)
        and (args.role is None or info.role == args.role)
        and (args.tag is None or args.tag in info.tags)
    ]
    if not selected:
        print("Khong co thiet bi nao khop bo loc.")
        return 0
    for info in selected:
        tags = ",".join(info.tags) or "-"
        print(f"{info.name:<12} {info.host:<15} {info.platform:<8} port={info.port} "
              f"group={info.group} role={info.role} tags={tags}")
    return 0


# ---------- collect (TV3) ----------

def cmd_collect(args) -> int:
    infos = _select_devices(_load_inventory(args.inventory), args.device)
    collector = Collector()

    def operation(device) -> TaskResult:
        return collector.collect(device)

    results = _run_on_devices(infos, operation, demo=args.demo)

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = Collector.export_json(results, out_dir / "collect.json")
        csv_path = Collector.export_csv(results, out_dir / "collect.csv")
        print(f"Da xuat: {json_path} va {csv_path}")

    return _print_results(results)


# ---------- restore (TV5) ----------

def _latest_snapshot(backup_manager: BackupManager, device_name: str):
    snapshots = backup_manager.list_snapshots(device_name)
    if not snapshots:
        return None
    return max(snapshots, key=lambda s: BackupManager._parse_time(s.captured_at))


def cmd_restore(args) -> int:
    options = _write_options(args)
    infos = _select_devices(_load_inventory(args.inventory), args.device)
    backup_manager = BackupManager(backup_dir=str(args.backup_dir))
    restore_manager = RestoreManager(backup_manager=backup_manager)

    def operation(device) -> TaskResult:
        snapshot = (next((s for s in backup_manager.list_snapshots(device.info.name)
                          if s.snapshot_id == args.snapshot_id), None) if args.snapshot_id
                    else _latest_snapshot(backup_manager, device.info.name))
        if snapshot is None:
            return TaskResult(
                device=device.info.name, action="restore", success=False,
                message="Khong co snapshot backup de khoi phuc",
                error_code="NO_SNAPSHOT",
            )
        return restore_manager.restore(device, snapshot)

    results = _run_on_devices(infos, operation, demo=args.demo, **options)
    return _print_results(results)


# ---------- deploy (TV5) ----------

def _load_vars(path: Optional[str]) -> Dict:
    if not path:
        return {}
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("File bien (--vars-file) phai la mot JSON object")
    return data


def cmd_deploy(args) -> int:
    options = _write_options(args)
    infos = _select_devices(_load_inventory(args.inventory), args.device)
    variables = _load_vars(args.vars_file)
    verifier = None
    if args.expected_neighbor:
        if args.write_scope != 'ospf' or args.demo:
            raise ValueError('--expected-neighbor requires real --write-scope ospf')
        from services.verification import OSPFVerificationService
        from devices.ospf_adapter import ipv4
        if not 0 < args.convergence_timeout <= 600:
            raise ValueError('Convergence timeout must be in (0, 600]')
        verifier = OSPFVerificationService([ipv4(rid) for rid in args.expected_neighbor], args.convergence_timeout)
    config_manager = ConfigManager(
        backup_manager=BackupManager(backup_dir=str(args.backup_dir)),
        template_dir=str(args.template_dir),
        verifier=verifier,
    )

    if args.dry_run:
        # Dry-run chi render template, khong ket noi thiet bi.
        if options['write']:
            from devices.write_adapter import WriteSSHAdapter
            from devices.ospf_adapter import OSPFSSHAdapter
            adapter = OSPFSSHAdapter if args.write_scope == 'ospf' else WriteSSHAdapter
            devices = [adapter(info, frr_shell='linux') for info in infos]
        else:
            devices = [DeviceFactory.create(info, demo=True) for info in infos]
        results = config_manager.dry_run(devices, args.template, variables)
        if options['write']:
            for device, result in zip(devices, results):
                if result.success:
                    device.validate_config_commands(config_manager._commands(result.data['rendered_config']))
        for result in results:
            if result.success:
                print(f"--- {result.device} ---")
                print(result.data.get("rendered_config", ""))
        return _print_results(results)

    def operation(device) -> TaskResult:
        return config_manager.deploy([device], args.template, variables)[0]

    results = _run_on_devices(infos, operation, demo=args.demo, **options)
    return _print_results(results)


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Network Backup System: TV3 + TV5 CLI")
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY),
                        help="File inventory YAML/JSON (mac dinh: data/inventory.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="Xem inventory")
    inv_sub = inv.add_subparsers(dest="inventory_command", required=True)
    inv_list = inv_sub.add_parser("list", help="Liet ke thiet bi")
    inv_list.add_argument("--group")
    inv_list.add_argument("--role")
    inv_list.add_argument("--tag")
    inv_list.set_defaults(func=cmd_inventory_list)

    collect = sub.add_parser("collect", help="Thu thap thong tin thiet bi (TV3)")
    collect.add_argument("--device", action="append", help="Ten thiet bi (lap lai duoc)")
    collect.add_argument("--out-dir", help="Thu muc xuat collect.json va collect.csv")
    collect.add_argument("--demo", action="store_true", help="Dung FakeDevice")
    collect.set_defaults(func=cmd_collect)

    restore = sub.add_parser("restore", help="Khoi phuc snapshot moi nhat (TV5)")
    restore.add_argument("--device", action="append", help="Ten thiet bi (lap lai duoc)")
    restore.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    restore.add_argument("--demo", action="store_true", help="Dung FakeDevice")
    restore.add_argument("--snapshot-id")
    restore.set_defaults(func=cmd_restore)

    deploy = sub.add_parser("deploy", help="Render va day cau hinh tu template (TV5)")
    deploy.add_argument("--template", required=True, help="Ten template, vi du: ospf")
    deploy.add_argument("--device", action="append", help="Ten thiet bi (lap lai duoc)")
    deploy.add_argument("--vars-file", help="File JSON chua bien cho template")
    deploy.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    deploy.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    deploy.add_argument("--dry-run", action="store_true", help="Chi render, khong day cau hinh")
    deploy.add_argument("--demo", action="store_true", help="Dung FakeDevice")
    deploy.add_argument('--expected-neighbor', action='append', help='Expected OSPF router ID; repeat for all peers')
    deploy.add_argument('--convergence-timeout', type=float, default=90)
    deploy.set_defaults(func=cmd_deploy)

    for command in (restore, deploy):
        command.add_argument('--write-scope', choices=['managed', 'ospf'],
                             help='managed: identity/description; ospf: OSPFv2 backbone running configuration')
        command.add_argument('--known-hosts')
        command.add_argument('--confirm-write', action='store_true')

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError, FileNotFoundError, DeviceCommandError) as exc:
        message = exc.args[0] if exc.args else exc
        print(f"[LOI] {message}", file=sys.stderr)
        return 2


def _use_utf8_console() -> None:
    """Console Windows mac dinh cp1252 se loi khi in tieng Viet."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _use_utf8_console()
    sys.exit(main())
