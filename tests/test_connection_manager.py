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