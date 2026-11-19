"""TV5 tests: no GNS3 required."""
import hashlib
from dataclasses import replace

import pytest

from core.fake_device import FakeDevice
from core.models import ConfigSnapshot, DeviceInfo, TaskResult
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager
from services.verification import VerificationService


@pytest.fixture
def device():
    dev = FakeDevice(DeviceInfo("R1", "192.0.2.11", "mikrotik"))
    dev.connect()
    yield dev
    dev.disconnect()


@pytest.fixture
def variables():
    return {"router_id": "1.1.1.1", "networks": [{"prefix": "10.0.0.0/24"}]}


def snapshot(dev, *, content=None, **changes):
    content = content if content is not None else dev.get_running_config()
    base = ConfigSnapshot(snapshot_id="R1_test", device_name=dev.info.name,
                          platform=dev.info.platform, captured_at="2026-11-16T17:00:00+07:00",
                          content=content, sha256=hashlib.sha256(content.encode()).hexdigest())
    return replace(base, **changes)


def test_dry_run_does_not_change_device(device, variables, tmp_path):
    original = device.get_running_config()
    result = ConfigManager().dry_run([device], "ospf", variables)[0]
    assert result.success
    assert "router-id=" in result.data["rendered_config"]
    assert device.get_running_config() == original
    assert not list(tmp_path.iterdir())


def test_unknown_template_must_not_fallback_to_ospf(device, variables):
    result = ConfigManager().dry_run([device], "nonexistent", variables)[0]
    assert not result.success


def test_missing_template_variables_fail_early(device):
    result = ConfigManager().dry_run([device], "ospf", {"router_id": "1.1.1.1"})[0]
    assert not result.success


def test_deploy_without_backup_is_blocked(device, variables):
    before = device.get_running_config()
    result = ConfigManager().deploy([device], "ospf", variables)[0]
    assert not result.success
    assert not result.data["push_started"]
    assert device.get_running_config() == before


def test_failed_backup_must_not_push_or_rollback(device, variables):
    class FailedBackup:
        def backup(self, dev):
            return TaskResult(dev.info.name, "backup", False, "disk full")
        def list_snapshots(self, name):
            raise AssertionError("list_snapshots must not be called")

    before = device.get_running_config()
    result = ConfigManager(backup_manager=FailedBackup()).deploy([device], "ospf", variables)[0]
    assert not result.success
    assert not result.data["push_started"]
    assert not result.data["rollback_attempted"]
    assert device.get_running_config() == before


def test_new_snapshot_must_be_selected_by_id(device, variables):
    class MismatchedBackup:
        def backup(self, dev):
            return TaskResult(dev.info.name, "backup", True, "ok", data={"snapshot_id": "new"})
        def list_snapshots(self, name):
            return [snapshot(device, snapshot_id="old")]

    before = device.get_running_config()
    result = ConfigManager(backup_manager=MismatchedBackup()).deploy([device], "ospf", variables)[0]
    assert not result.success
    assert not result.data["push_started"]
    assert device.get_running_config() == before


def test_deploy_success_and_verified_with_real_backup_manager(device, variables, tmp_path):
    manager = BackupManager(str(tmp_path / "backups"))
    result = ConfigManager(backup_manager=manager).deploy([device], "ospf", variables)[0]
    assert result.success
    assert result.data["verified"] is True
    assert len(manager.list_snapshots("R1")) == 1
    assert "router-id=1.1.1.1" in device.get_running_config()


def test_failed_push_triggers_rollback(device, variables, tmp_path):
    device.fail_push = True
    old = device.get_running_config()
    manager = BackupManager(str(tmp_path))
    result = ConfigManager(backup_manager=manager).deploy([device], "ospf", variables)[0]
    assert not result.success
    assert result.data["rollback_attempted"]
    assert result.data["rolled_back"]
    assert device.get_running_config() == old


def test_rollback_failure_does_not_report_success(device, variables, tmp_path):
    device.fail_push = True
    device.fail_restore = True
    result = ConfigManager(backup_manager=BackupManager(str(tmp_path))).deploy([device], "ospf", variables)[0]
    assert not result.success
    assert result.data["rollback_attempted"]
    assert not result.data["rolled_back"]
    assert result.data["rollback_error"]


def test_post_deploy_verification_failure_triggers_rollback(device, variables, tmp_path):
    class RejectVerifier(VerificationService):
        def verify_commands_present(self, dev, commands):
            return {"passed": False, "missing_lines": ["not applied"]}

    old = device.get_running_config()
    verifier = RejectVerifier()
    result = ConfigManager(backup_manager=BackupManager(str(tmp_path)), verifier=verifier).deploy([device], "ospf", variables)[0]
    assert not result.success
    assert result.data["rolled_back"]
    assert device.get_running_config() == old


@pytest.mark.parametrize("bad_change", [
    {"device_name": "OTHER"},
    {"platform": "frr"},
    {"sha256": "0" * 64},
    {"content": ""},
    {"scope": "unknown-scope"},
])
def test_restore_rejects_invalid_snapshots(device, bad_change):
    original = device.get_running_config()
    bad = snapshot(device, **bad_change)
    assert not RestoreManager().restore(device, bad).success
    assert device.get_running_config() == original


def test_restore_exact_success(device):
    original = device.get_running_config()
    snap = snapshot(device)
    device.push_config(["new command"])
    result = RestoreManager().restore(device, snap)
    assert result.success
    assert result.data["exact_hash_match"]
    assert device.get_running_config() == original


def test_restore_rejects_extra_lines_after_restore(device):
    class InexactRestore(FakeDevice):
        def restore_config(self, backup):
            self._config = backup + "unwanted extra\n"
            return True

    fake = InexactRestore(device.info)
    fake.connect()
    snap = snapshot(fake)
    result = RestoreManager().restore(fake, snap)
    assert not result.success
    assert result.error_code == "RESTORE_VERIFY_FAILED"
    fake.disconnect()


def test_verification_subset_no_longer_passes_restore(device):
    expected = device.get_running_config()
    device.push_config(["another command"])
    verification = VerificationService().verify_config_match(device, expected)
    assert not verification["passed"]
    assert verification["unexpected_lines"] == ["another command"]


def test_literal_command_verification_uses_complete_lines(device):
    device.push_config(["router ospf 123"])
    checked = VerificationService().verify_commands_present(device, ["router ospf 1"])
    assert not checked["passed"]


def test_deploy_separates_devices_success_and_failure(variables, tmp_path):
    good = FakeDevice(DeviceInfo("R1", "192.0.2.11", "mikrotik"))
    bad = FakeDevice(DeviceInfo("R2", "192.0.2.12", "mikrotik"), fail_push=True)
    for d in (good, bad):
        d.connect()
    try:
        results = ConfigManager(backup_manager=BackupManager(str(tmp_path))).deploy([good, bad], "ospf", variables)
        assert [r.success for r in results] == [True, False]
        assert results[1].data["rolled_back"]
    finally:
        for d in (good, bad):
            d.disconnect()
