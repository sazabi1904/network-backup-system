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