"""Exercise Inventory, Factory, SSHAdapter, Collector and CLI with mock SSH I/O."""
import csv
import json
from threading import Barrier
from unittest.mock import Mock

import pytest
import yaml
from netmiko.exceptions import NetmikoAuthenticationException, ReadTimeout

from core.exceptions import DeviceCommandError
from core.factory import DeviceFactory
from core.models import DeviceInfo
from devices.ssh_adapter import SSHAdapter, register_device_adapters
from main import main
from services.collector import Collector
from services.connection_manager import ConnectionManager
from services.inventory import InventoryManager


MT_OUTPUTS = {
    "/system resource print": (
        "version: 7.23.8\nuptime: 1d\ncpu: QEMU\ncpu-count: 1\n"
        "cpu-load: 2%\ntotal-memory: 1024MiB\nfree-memory: 512MiB\n"
    ),
    "/system routerboard print": "routerboard: no\n",
    "/interface print terse without-paging": "0 R name=ether1 actual-mtu=1500\n",
    "/ip route print terse without-paging": "0 A dst-address=10.0.0.0/24 gateway=192.0.2.2\n",
    "/ip arp print terse without-paging": "",
    "/interface bridge host print terse without-paging": "Flags: D - dynamic\n",
    "/ip neighbor print terse without-paging": "0 interface=ether1 identity=R2 platform=MikroTik\n",
    "/routing ospf neighbor print terse without-paging": "0 D router-id=2.2.2.2 state=Full\n",
}
FRR_OUTPUTS = {
    "show version": "FRRouting 8.2.2 (R3).\n",
    "show interface json": '{"eth0": {"state": "up"}}',
    "show ip route json": '{"10.0.0.0/24": [{"protocol": "ospf"}]}',
    "show ip ospf neighbor json": '{"2.2.2.2": {"state": "Full"}}',
}


@pytest.fixture
def ssh_lab(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LAB_USERNAME", "backup")
    monkeypatch.setenv("LAB_PASSWORD", "test-only-secret")
    monkeypatch.setattr(DeviceFactory, "_registry", {})
    sessions = {}
    params = []
    failures = {}
    outputs = {"mikrotik_routeros": dict(MT_OUTPUTS), "linux": dict(FRR_OUTPUTS)}
    lab = {"sessions": sessions, "params": params, "failures": failures, "outputs": outputs,
           "barrier": None, "direct_vtysh": False}

    def connect(**kwargs):
        params.append(kwargs)
        if lab["barrier"] is not None:
            lab["barrier"].wait(timeout=5)
        if kwargs["host"] in failures:
            raise failures[kwargs["host"]]
        session = Mock()
        profile = outputs[kwargs["device_type"]]

        def send(command, **options):
            if command.startswith('vtysh -c "'):
                if lab["direct_vtysh"]:
                    return "% Unknown command: vtysh\n"
                command = command[len('vtysh -c "'):-1]
            output = profile[command]
            if isinstance(output, Exception):
                raise output
            return output

        session.send_command.side_effect = send
        sessions[kwargs["host"]] = session
        return session

    monkeypatch.setattr("devices.ssh_adapter.ConnectHandler", connect)
    return lab


def write_inventory(path, count=2):
    entries = [
        {"name": "MT-R1", "host": "192.0.2.11", "platform": "mikrotik", "group": "lab", "tags": ["core"]},
        {"name": "FRR-R3", "host": "192.0.2.13", "platform": "frr", "group": "lab", "tags": ["edge"]},
        {"name": "MT-R2", "host": "192.0.2.12", "platform": "mikrotik", "group": "lab"},
        {"name": "FRR-R4", "host": "192.0.2.14", "platform": "frr", "group": "lab"},
    ][:count]
    path.write_text(yaml.safe_dump(entries), encoding="utf-8")
    return path


@pytest.mark.parametrize("shell,direct", [("linux", False), ("vtysh", True), ("auto", True)])
def test_cli_collects_both_platforms_and_exports(tmp_path, ssh_lab, shell, direct):
    ssh_lab["direct_vtysh"] = direct
    inventory = write_inventory(tmp_path / "inventory.yaml")
    output = tmp_path / "reports"
    with pytest.raises(SystemExit) as result:
        main(["--collect", "--inventory", str(inventory), "--output-dir", str(output),
              "--timeout", "9", "--known-hosts", "verified_hosts", "--frr-shell", shell])
    assert result.value.code == 0
    records = json.loads((output / "collection.json").read_text())
    assert [record["device"] for record in records] == ["MT-R1", "FRR-R3"]
    mt, frr = records
    assert mt["sections"]["interfaces"]["data"][0]["name"] == "ether1"
    assert mt["sections"]["arp"] == {"status": "success", "data": [], "error_code": None}
    assert mt["sections"]["serial"]["status"] == "unsupported"
    assert mt["sections"]["ospf"]["data"][0]["state"] == "Full"
    assert frr["sections"]["interfaces"]["data"]["eth0"]["state"] == "up"
    assert frr["sections"]["routes"]["data"]["10.0.0.0/24"][0]["protocol"] == "ospf"
    assert frr["sections"]["ospf"]["data"]["2.2.2.2"]["state"] == "Full"
    assert frr["sections"]["arp"]["status"] == "unsupported"
    with (output / "collection.csv").open(encoding="utf-8-sig") as report:
        assert len(list(csv.DictReader(report))) == 2
    for params in ssh_lab["params"]:
        assert params["username"] == "backup"
        assert params["ssh_strict"] is True
        assert params["alt_key_file"] == "verified_hosts"
        assert params["conn_timeout"] == 9
    for session in ssh_lab["sessions"].values():
        session.disconnect.assert_called_once()
        assert all(call.kwargs["read_timeout"] == 9 for call in session.send_command.call_args_list)
    for path in output.iterdir():
        text = path.read_text(encoding="utf-8-sig")
        assert "test-only-secret" not in text
        assert "credential_ref" not in text
        assert "raw_sections" not in text


def test_concurrent_collection_isolates_auth_failure(tmp_path, ssh_lab):
    inventory = InventoryManager(write_inventory(tmp_path / "inventory.yaml", count=4))
    infos = inventory.load()
    ssh_lab["barrier"] = Barrier(4)
    ssh_lab["failures"]["192.0.2.12"] = NetmikoAuthenticationException("test-only-secret")
    register_device_adapters()
    results = ConnectionManager(max_workers=4).run(infos, operation=Collector().collect)
    assert [result.device for result in results] == [info.name for info in infos]
    assert [result.success for result in results] == [True, True, False, True]
    assert results[2].data["connection_status"] == "authentication_failed"
    assert results[2].error_code == "DeviceAuthenticationError"
    assert "test-only-secret" not in str(results)
    for session in ssh_lab["sessions"].values():
        session.disconnect.assert_called_once()


@pytest.mark.parametrize("output,status", [
    ("bad command name route (line 1 column 5)", "unsupported"),
    ("failure: permission denied test-only-secret", "error"),
])
def test_command_failure_keeps_later_sections(ssh_lab, output, status):
    ssh_lab["outputs"]["mikrotik_routeros"]["/ip route print terse without-paging"] = output
    register_device_adapters()
    result = ConnectionManager().run(
        [DeviceInfo("R1", "192.0.2.11", "mikrotik")], operation=Collector().collect,
    )[0]
    sections = result.data["sections"]
    assert sections["routes"]["status"] == status
    assert sections["arp"]["status"] == "success"
    assert sections["ospf"]["data"][0]["state"] == "Full"
    assert "test-only-secret" not in str(result)
    ssh_lab["sessions"]["192.0.2.11"].disconnect.assert_called_once()


def test_read_timeout_closes_session_and_cli_reports_partial_error(tmp_path, ssh_lab):
    ssh_lab["outputs"]["mikrotik_routeros"]["/ip route print terse without-paging"] = ReadTimeout("test-only-secret")
    inventory = write_inventory(tmp_path / "inventory.yaml")
    with pytest.raises(SystemExit) as result:
        main(["--collect", "--inventory", str(inventory)])
    assert result.value.code == 1
    records = json.loads((tmp_path / "reports/tv2-tv3/collection.json").read_text())
    assert records[0]["sections"]["routes"]["error_code"] == "DeviceTimeoutError"
    assert records[1]["sections"]["routes"]["status"] == "success"
    for session in ssh_lab["sessions"].values():
        session.disconnect.assert_called_once()


def test_frr_unsupported_command_keeps_linux_shell_and_later_sections(ssh_lab):
    ssh_lab["outputs"]["linux"]["show ip route json"] = "% Unknown command: show ip route json\n"
    register_device_adapters()
    result = ConnectionManager().run(
        [DeviceInfo("R3", "192.0.2.13", "frr")], operation=Collector().collect,
    )[0]
    assert result.data["sections"]["routes"]["status"] == "unsupported"
    assert result.data["sections"]["ospf"]["status"] == "success"
    session = ssh_lab["sessions"]["192.0.2.13"]
    assert all(call.args[0].startswith("vtysh -c ") for call in session.send_command.call_args_list)


def test_connection_only_filters_inventory_without_sending_commands(tmp_path, ssh_lab):
    inventory = write_inventory(tmp_path / "inventory.yaml")
    with pytest.raises(SystemExit) as result:
        main(["--check-connections", "--inventory", str(inventory), "--tag", "edge", "--group", "lab"])
    assert result.value.code == 0
    assert set(ssh_lab["sessions"]) == {"192.0.2.13"}
    session = ssh_lab["sessions"]["192.0.2.13"]
    session.send_command.assert_not_called()
    session.disconnect.assert_called_once()
    assert (tmp_path / "reports/tv2-tv3/connections.json").exists()


@pytest.mark.parametrize("args", [
    ["--collect"], ["--collect", "--inventory", "x", "--timeout", "nan"],
    ["--collect", "--inventory", "x", "--workers", "0"],
    ["--demo", "--collect"], ["--inventory", "x"],
])
def test_cli_rejects_invalid_options_before_connecting(ssh_lab, args):
    with pytest.raises(SystemExit) as result:
        main(args)
    assert result.value.code == 2
    assert not ssh_lab["params"]


@pytest.mark.parametrize("platform,command", [
    ("mikrotik", "/system reboot"),
    ("mikrotik", "/ip route print terse without-paging; /system reboot"),
    ("frr", "configure terminal"),
    ("frr", "show interface json; reboot"),
])
def test_only_exact_read_commands_reach_transport(ssh_lab, platform, command):
    with SSHAdapter(DeviceInfo("R1", "192.0.2.11", platform)) as device:
        with pytest.raises(DeviceCommandError):
            device.send_command(command)
    ssh_lab["sessions"]["192.0.2.11"].send_command.assert_not_called()
