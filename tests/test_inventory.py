import json
import pytest

from core.models import DeviceInfo
from services.inventory import InventoryManager


@pytest.mark.parametrize("extension", [".json", ".yaml"])
def test_save_reload_preserves_changes(tmp_path, monkeypatch, extension):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / f"inventory{extension}"
    inventory = InventoryManager(path)

    inventory.add_device(DeviceInfo(
        name="R1",
        host="192.0.2.11",
        platform="mikrotik",
        group="nhom-a",
        tags=("ospf",),
    ))
    inventory.add_device(DeviceInfo(
        name="R2",
        host="192.0.2.12",
        platform="frr",
    ))
    inventory.save()

    inventory.update_device("R1", port=2222, group="nhom-b")
    inventory.remove_device("R2")
    inventory.save()

    reloaded = InventoryManager(path)
    devices = reloaded.load()

    assert devices == inventory.list_devices()
    assert [device.name for device in devices] == ["R1"]
    assert devices[0].port == 2222
    assert devices[0].group == "nhom-b"
    assert devices[0].tags == ("ospf",)

@pytest.mark.parametrize("bad_port", [0, 65536, 22.5, True, "22", None])
def test_invalid_port_keeps_inventory(tmp_path, monkeypatch, bad_port):
    monkeypatch.chdir(tmp_path)
    inventory = InventoryManager(tmp_path / "inventory.json")
    inventory.add_device(
        DeviceInfo("R1", "192.0.2.11", "mikrotik")
    )
    before = inventory.list_devices()

    with pytest.raises(ValueError):
        inventory.update_device("R1", port=bad_port)

    assert inventory.list_devices() == before

@pytest.mark.parametrize("operation", ["load", "add", "update"])
@pytest.mark.parametrize("bad_host", ["not-an-ip", "999.0.0.1", "192.0.2", ""])
def test_invalid_ip_preserves_inventory(tmp_path, operation, bad_host):
    inventory = InventoryManager(tmp_path / "inventory.json")
    inventory.add_device(DeviceInfo("R1", "192.0.2.11", "mikrotik"))
    before = inventory.list_devices()
    if operation == "load":
        inventory.path.write_text(json.dumps([
            {"name": "R2", "host": bad_host, "platform": "frr"},
        ]), encoding="utf-8")
    with pytest.raises(ValueError):
        if operation == "load":
            inventory.load()
        elif operation == "add":
            inventory.add_device(DeviceInfo("R2", bad_host, "frr"))
        else:
            inventory.update_device("R1", name="renamed", host=bad_host)
    assert inventory.list_devices() == before


@pytest.mark.parametrize("host", ["192.0.2.12", "2001:db8::1"])
def test_valid_ip_round_trip(tmp_path, host):
    inventory = InventoryManager(tmp_path / "inventory.json")
    inventory.add_device(DeviceInfo("R1", host, "mikrotik"))
    inventory.update_device("R1", host=host)
    expected = inventory.list_devices()
    inventory.save()
    assert InventoryManager(inventory.path).load() == expected
