from threading import Barrier

from core.fake_device import FakeDevice
from core.models import DeviceInfo, TaskResult
from services.connection_manager import ConnectionManager

import pytest

from core.exceptions import (
    DeviceAuthenticationError,
    DeviceConnectionError,
    DeviceTimeoutError,
)


def test_four_connections_run_together_and_close(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    barrier = Barrier(4)

    class ParallelDevice(FakeDevice):
        def connect(self):
            barrier.wait(timeout=5)
            super().connect()

        def disconnect(self):
            super().disconnect()
            self.was_disconnected = True

    infos = [
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        DeviceInfo("R2", "192.0.2.12", "mikrotik"),
        DeviceInfo("R3", "192.0.2.13", "frr"),
        DeviceInfo("R4", "192.0.2.14", "frr"),
    ]
    adapters = {
        info.name: ParallelDevice(info)
        for info in infos
    }

    def fake_create(info, demo=False):
        return adapters[info.name]

    monkeypatch.setattr(
        "services.connection_manager.DeviceFactory.create",
        fake_create,
    )

    manager = ConnectionManager(max_workers=4, demo=True)
    results = manager.run(infos)

    assert [result.device for result in results] == ["R1", "R2", "R3", "R4"]
    assert all(result.success for result in results)
    assert all(
        getattr(adapter, "was_disconnected", False)
        for adapter in adapters.values()
    )

@pytest.mark.parametrize(
    "error_type,status",
    [
        (DeviceConnectionError, "offline"),
        (DeviceTimeoutError, "timeout"),
        (DeviceAuthenticationError, "authentication_failed"),
    ],
)
def test_router_failure_is_isolated(tmp_path, monkeypatch, error_type, status):
    monkeypatch.chdir(tmp_path)

    class FaultyDevice(FakeDevice):
        def connect(self):
            if self.info.name == "R2":
                raise error_type("Simulated connection failure")
            super().connect()

    infos = [
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        DeviceInfo("R2", "192.0.2.12", "mikrotik"),
        DeviceInfo("R3", "192.0.2.13", "frr"),
        DeviceInfo("R4", "192.0.2.14", "frr"),
    ]

    def fake_create(info, demo=False):
        return FaultyDevice(info)

    monkeypatch.setattr(
        "services.connection_manager.DeviceFactory.create",
        fake_create,
    )

    manager = ConnectionManager(max_workers=4, demo=True)
    results = manager.run(infos)

    assert [r.device for r in results] == ["R1", "R2", "R3", "R4"]

    failed = results[1]
    assert failed.success is False
    assert failed.data["connection_status"] == status
    assert failed.error_code == error_type.__name__
    assert all(r.success for r in results if r.device != "R2")

def test_operation_receives_connected_device(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    info = DeviceInfo("R1", "192.0.2.11", "mikrotik")

    def collect_probe(device):
        device.send_command("/system resource print")
        return TaskResult(
            device=device.info.name,
            action="collect",
            success=True,
            message="OK",
            data={"marker": "retained"},
        )

    manager = ConnectionManager(demo=True)
    result = manager.run([info], operation=collect_probe)[0]

    assert result.success is True
    assert result.action == "collect"
    assert result.data["marker"] == "retained"
    assert result.data["connection_status"] == "online"
    assert result.data["device_info"]["host"] == info.host

@pytest.mark.parametrize("fail_init", [False, True])
@pytest.mark.parametrize("error_type", [OSError, PermissionError])
def test_logging_failure_preserves_results(monkeypatch, fail_init, error_type):
    class BrokenLogger:
        def __init__(self):
            if fail_init:
                raise error_type("sensitive detail")

        def log(self, *args, **kwargs):
            raise error_type("sensitive detail")

    monkeypatch.setattr("services.connection_manager.AuditLogger", BrokenLogger)
    results = ConnectionManager(demo=True).run([
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        DeviceInfo("R2", "192.0.2.12", "frr"),
    ])
    assert [result.device for result in results] == ["R1", "R2"]
    assert all(result.success for result in results)
    assert all(result.data["logging_error"] == error_type.__name__ for result in results)
    assert "sensitive detail" not in str(results)


def test_disconnect_log_failure_preserves_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class DisconnectFailure(FakeDevice):
        def disconnect(self):
            super().disconnect()
            raise DeviceConnectionError("sensitive disconnect detail")

    monkeypatch.setattr(
        "services.connection_manager.DeviceFactory.create",
        lambda info, demo=False: DisconnectFailure(info),
    )
    manager = ConnectionManager(demo=True)
    logged_actions = []

    def fail_disconnect_log(*args, **kwargs):
        logged_actions.append(args[2])
        if args[2] == "disconnect":
            raise PermissionError("sensitive log detail")

    monkeypatch.setattr(manager.logger, "log", fail_disconnect_log)
    result = manager.run([DeviceInfo("R1", "192.0.2.11", "mikrotik")])[0]
    assert result.success is True
    assert logged_actions == ["check_connection", "disconnect"]
    assert result.data["disconnect_error"] == "DeviceConnectionError"
    assert result.data["logging_error"] == "PermissionError"
    assert "sensitive" not in str(result)
