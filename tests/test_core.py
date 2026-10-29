import json
from pathlib import Path
import pytest
from core.base import NetworkDevice
from core.exceptions import DeviceCommandError, DeviceConnectionError, DeviceRestoreError
from core.factory import DeviceFactory
from core.fake_device import FakeDevice
from core.models import DeviceInfo
from services.logger import AuditLogger
from main import make_demo_devices, run_self_test


def sample_info():
    return DeviceInfo("R1", "192.0.2.11", "mikrotik")


def test_cannot_instantiate_abstract_device():
    with pytest.raises(TypeError):
        NetworkDevice(sample_info())


def test_fake_device_backup_change_restore():
    d = FakeDevice(sample_info())
    with pytest.raises(DeviceConnectionError):
        d.get_running_config()
    d.connect()
    old = d.get_running_config()
    assert d.push_config(["router ospf 1"]) == "FAKE: applied"
    assert "ospf" in d.get_running_config()
    assert d.restore_config(old) is True
    assert d.get_running_config() == old
    d.disconnect()


def test_fake_device_failure_paths():
    d = FakeDevice(sample_info(), fail_connect=True)
    with pytest.raises(DeviceConnectionError):
        d.connect()
    d = FakeDevice(sample_info(), fail_push=True, fail_restore=True)
    d.connect()
    with pytest.raises(DeviceCommandError):
        d.push_config(["x"])
    with pytest.raises(DeviceRestoreError):
        d.restore_config("baseline")


def test_factory_fake_and_real_adapter_contract(monkeypatch):
    DeviceFactory._registry = {}
    assert isinstance(DeviceFactory.create(sample_info(), demo=True), FakeDevice)
    with pytest.raises(ValueError, match="Chua dang ky adapter"):
        DeviceFactory.create(sample_info())
    DeviceFactory.register("mikrotik", FakeDevice)
    assert isinstance(DeviceFactory.create(sample_info()), NetworkDevice)


def test_audit_redacts_secret(tmp_path):
    f = tmp_path / "audit.jsonl"
    audit = AuditLogger(f)
    audit.log("tv1", "R1", "push", True,
              commands=["router ospf 1", "set password SECRET123"])
    raw = f.read_text(encoding="utf-8")
    assert "SECRET123" not in raw
    event = json.loads(raw)
    assert event["commands"][1] == "[REDACTED SENSITIVE COMMAND]"
    assert event["device"] == "R1"


def test_demo_inventory_four_devices():
    devices = make_demo_devices()
    assert len(devices) == 4
    assert set(devices) == {"R1", "R2", "R3", "R4"}


def test_self_test_runs(tmp_path):
    assert run_self_test(AuditLogger(tmp_path / "audit.jsonl"))
