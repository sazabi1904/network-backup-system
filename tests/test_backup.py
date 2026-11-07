from pathlib import Path

import pytest

from core.fake_device import FakeDevice
from core.models import DeviceInfo
from services.backup_manager import BackupManager


def test_read_snapshot_rejects_changed_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    manager = BackupManager()
    device = FakeDevice(
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        initial_config="hostname R1\n",
    )

    result = manager.backup_with_connection(device)
    assert result.success

    path = Path(result.data["path"])
    snapshot_id = path.stem

    snapshot = manager.read_snapshot(snapshot_id)
    assert snapshot.content == "hostname R1\n"

    path.write_text("hostname CHANGED\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        manager.read_snapshot(snapshot_id)