import json
from pathlib import Path

import pytest

import cli
from core.exceptions import DeviceRestoreError
from core.fake_device import FakeDevice
from core.models import DeviceInfo
from services.backup_manager import BackupManager
from services.restore import RestoreManager
from services.config_manager import ConfigManager

PROJECT_DIR = Path(__file__).resolve().parents[1]
INVENTORY = str(PROJECT_DIR / "data" / "inventory.yaml")


@pytest.fixture
def ospf_vars(tmp_path) -> str:
    path = tmp_path / "ospf.json"
    path.write_text(
        json.dumps({"router_id": "1.1.1.1", "networks": [{"prefix": "10.0.0.0/24"}]}),
        encoding="utf-8",
    )
    return str(path)


def test_restore_and_config_modules_import_without_errors():
    # Regression: truoc day services/restore.py import services.exceptions (khong ton tai).
    assert RestoreManager is not None
    assert ConfigManager is not None
    assert issubclass(DeviceRestoreError, Exception)


def test_inventory_list_shows_all_devices(capsys):
    assert cli.main(["--inventory", INVENTORY, "inventory", "list"]) == 0
    out = capsys.readouterr().out
    for name in ("R1", "R2", "R3", "R4"):
        assert name in out


def test_inventory_list_filters_by_group(capsys):
    assert cli.main(["--inventory", INVENTORY, "inventory", "list", "--group", "nhom-b"]) == 0
    out = capsys.readouterr().out
    assert "R3" in out and "R4" in out
    assert "R1" not in out and "R2" not in out


def test_unknown_device_returns_error_code(capsys):
    assert cli.main(["--inventory", INVENTORY, "restore", "--demo", "--device", "NOPE"]) == 2
    assert "NOPE" in capsys.readouterr().err


def test_deploy_dry_run_renders_both_platforms(ospf_vars, capsys):
    rc = cli.main([
        "--inventory", INVENTORY, "deploy", "--template", "ospf",
        "--device", "R1", "--device", "R3",
        "--vars-file", ospf_vars, "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "router-id=1.1.1.1" in out      # MikroTik R1
    assert "ospf router-id 1.1.1.1" in out  # FRR R3


def test_deploy_demo_pushes_config(ospf_vars, tmp_path, capsys):
    rc = cli.main([
        "--inventory", INVENTORY, "deploy", "--template", "ospf",
        "--device", "R1", "--vars-file", ospf_vars, "--demo",
        "--backup-dir", str(tmp_path / "backups"),
    ])
    assert rc == 0
    assert "deploy" in capsys.readouterr().out


def test_restore_without_snapshot_fails(tmp_path, capsys):
    rc = cli.main([
        "--inventory", INVENTORY, "restore", "--demo", "--device", "R1",
        "--backup-dir", str(tmp_path / "empty"),
    ])
    assert rc == 1
    assert "NO_SNAPSHOT" in capsys.readouterr().out


def test_backup_then_restore_roundtrip_demo(tmp_path, capsys):
    backup_dir = tmp_path / "backups"
    device = FakeDevice(DeviceInfo(name="R1", host="192.0.2.11", platform="mikrotik"))
    device.connect()
    assert BackupManager(backup_dir=str(backup_dir)).backup(device).success

    rc = cli.main([
        "--inventory", INVENTORY, "restore", "--demo", "--device", "R1",
        "--backup-dir", str(backup_dir),
    ])
    assert rc == 0
    assert "OK" in capsys.readouterr().out
