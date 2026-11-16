from copy import deepcopy
from core.fake_device import FakeDevice
from core.models import DeviceInfo, TaskResult
from services.collector import Collector
from services.connection_manager import ConnectionManager
import json
import csv
from core.exceptions import DeviceConnectionError


class ScriptedDevice(FakeDevice):
    """Thiết bị giả trả output riêng cho từng lệnh."""

    def __init__(self, info, outputs):
        super().__init__(info)
        self.outputs = outputs

    def send_command(self, command):
        self._require_connection()
        return self.outputs[command]

def test_mikrotik_collection_normalizes_sections():
    outputs = {
        "/system resource print": """
            version: 7.16.2
            uptime: 1d02:03:04
            cpu: QEMU
            cpu-count: 1
            cpu-load: 5%
            total-memory: 128.0MiB
            free-memory: 64.0MiB
        """,
        "/system routerboard print": """
            routerboard: yes
            serial-number: ABCD1234
        """,
        "/interface print terse without-paging":
            "0 R name=ether1 actual-mtu=1500",
        "/ip route print terse without-paging":
            "0 A dst-address=0.0.0.0/0 gateway=192.0.2.1",
        "/ip arp print terse without-paging":
            "0 D address=192.0.2.2 mac-address=AA:BB:CC:DD:EE:FF",
        "/interface bridge host print terse without-paging":
            "0 D mac-address=AA:BB:CC:DD:EE:FF bridge=bridge1",
        "/ip neighbor print terse without-paging":
            "0 interface=ether1 identity=R2 platform=MikroTik",
        "/routing ospf neighbor print terse without-paging":
            "0 D router-id=2.2.2.2 state=Full",
    }

    device = ScriptedDevice(
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        outputs,
    )

    try:
        device.connect()
        result = Collector().collect(device)
    finally:
        device.disconnect()

    sections = result.data["sections"]

    assert result.success is True
    assert result.data["summary"]["status"] == "success"
    assert set(sections) == set(Collector.SECTIONS)
    assert sections["serial"]["data"] == "ABCD1234"
    assert sections["interfaces"]["data"][0]["name"] == "ether1"
    assert sections["routes"]["data"][0]["dst_address"] == "0.0.0.0/0"
    assert sections["ospf"]["data"][0]["router_id"] == "2.2.2.2"
    assert len(result.data["commands"]) == 8

def test_frr_collection_normalizes_json_and_marks_unsupported():
    outputs = {
        "show version":
            "FRRouting 8.2.2 (R3).",
        "show interface json":
            '{"eth0": {"index": 2, "state": "up"}}',
        "show ip route json":
            '{"10.0.0.0/24": [{"protocol": "ospf"}]}',
        "show ip ospf neighbor json":
            '{"2.2.2.2": {"state": "Full"}}',
    }

    device = ScriptedDevice(
        DeviceInfo("R3", "192.0.2.13", "frr"),
        outputs,
    )

    try:
        device.connect()
        result = Collector().collect(device)
    finally:
        device.disconnect()

    sections = result.data["sections"]

    assert result.success is True
    assert result.data["summary"]["status"] == "partial"
    assert (
        sections["system"]["data"]["version"]["data"]
        == "8.2.2"
    )
    assert sections["interfaces"]["data"]["eth0"]["state"] == "up"
    assert "10.0.0.0/24" in sections["routes"]["data"]
    assert sections["ospf"]["data"]["2.2.2.2"]["state"] == "Full"
    assert sections["serial"]["status"] == "unsupported"
    assert sections["arp"]["status"] == "unsupported"
    assert sections["mac_table"]["status"] == "unsupported"
    assert sections["discovery"]["status"] == "unsupported"
    assert len(result.data["commands"]) == 4

def test_report_record_omits_raw_and_credentials():
    result = TaskResult(
        device="R1",
        action="collect",
        success=True,
        message="Đã đọc được một phần dữ liệu thiết bị",
        data={
            "device_info": {
                "name": "R1",
                "host": "192.0.2.11",
                "platform": "mikrotik",
                "port": 22,
                "group": "nhom-a",
                "role": "router",
                "tags": ("core", "ospf"),
                "credential_ref": "lab",
                "password": "khong-duoc-xuat",
            },
            "connection_status": "online",
            "collected_at": "2026-11-09T10:00:00+00:00",
            "summary": {
                "status": "partial",
            },
            "sections": {
                "system": {
                    "status": "success",
                    "data": {},
                    "error_code": None,
                },
            },
            "raw_sections": {
                "system": {
                    "status": "success",
                    "data": "raw output",
                    "error_code": None,
                },
            },
        },
    )

    record = Collector._build_report_record(result)

    assert record["device"] == "R1"
    assert record["host"] == "192.0.2.11"
    assert record["platform"] == "mikrotik"
    assert record["tags"] == ["core", "ospf"]
    assert record["connection_status"] == "online"
    assert record["summary_status"] == "partial"
    assert "raw_sections" not in record
    assert "credential_ref" not in record
    assert "password" not in record

def test_section_error_keeps_other_collected_data():
    outputs = {
        command: "Flags: D - dynamic"
        for command in Collector.COMMANDS["mikrotik"].values()
        if command is not None
    }

    outputs.update({
        "/system resource print": """
            version: 7.16.2
            uptime: 1d02:03:04
            cpu: QEMU
            cpu-count: 1
            cpu-load: 5%
            total-memory: 128.0MiB
            free-memory: 64.0MiB
        """,
        "/system routerboard print": """
            routerboard: yes
            serial-number: ABCD1234
        """,
        "/interface print terse without-paging":
            "0 R name=ether1 actual-mtu=1500",
        "/ip route print terse without-paging":
            "invalid route output",
    })

    device = ScriptedDevice(
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        outputs,
    )

    try:
        device.connect()
        result = Collector().collect(device)
    finally:
        device.disconnect()

    sections = result.data["sections"]

    assert result.success is True
    assert result.data["summary"]["status"] == "partial"
    assert result.error_code is None
    assert sections["routes"]["status"] == "error"
    assert sections["routes"]["error_code"] == "ValueError"
    assert sections["interfaces"]["status"] == "success"
    assert sections["interfaces"]["data"][0]["name"] == "ether1"
    assert sections["serial"]["data"] == "ABCD1234"

def test_export_json_writes_filtered_records(tmp_path):
    result = TaskResult(
        device="R1",
        action="collect",
        success=True,
        message="Đã đọc dữ liệu thiết bị",
        data={
            "device_info": {
                "name": "R1",
                "host": "192.0.2.11",
                "platform": "mikrotik",
                "port": 22,
                "group": "nhom-a",
                "role": "router",
                "tags": ("core",),
                "credential_ref": "lab",
            },
            "connection_status": "online",
            "collected_at": "2026-11-09T10:00:00+00:00",
            "summary": {
                "status": "success",
            },
            "sections": {
                "system": {
                    "status": "success",
                    "data": {},
                    "error_code": None,
                },
            },
            "raw_sections": {
                "system": {
                    "status": "success",
                    "data": "raw output",
                    "error_code": None,
                },
            },
        },
    )

    target = Collector.export_json(
        [result],
        tmp_path / "reports" / "devices.json",
    )

    payload = json.loads(
        target.read_text(encoding="utf-8")
    )

    assert target.exists()
    assert payload[0]["device"] == "R1"
    assert payload[0]["host"] == "192.0.2.11"
    assert payload[0]["summary_status"] == "success"

    serialized = json.dumps(payload)
    assert "credential_ref" not in serialized
    assert "raw output" not in serialized

def test_export_csv_writes_filtered_rows(tmp_path):
    result = TaskResult(
        device="R1",
        action="collect",
        success=True,
        message="Đã đọc dữ liệu thiết bị",
        data={
            "device_info": {
                "name": "R1",
                "host": "192.0.2.11",
                "platform": "mikrotik",
                "port": 22,
                "group": "nhom-a",
                "role": "router",
                "tags": ("core", "ospf"),
                "credential_ref": "lab",
            },
            "connection_status": "online",
            "collected_at": "2026-11-09T10:00:00+00:00",
            "summary": {
                "status": "success",
            },
            "sections": {
                "system": {
                    "status": "success",
                    "data": {"os": "RouterOS"},
                    "error_code": None,
                },
            },
            "raw_sections": {
                "system": {
                    "status": "success",
                    "data": "raw output",
                    "error_code": None,
                },
            },
        },
    )

    target = Collector.export_csv(
        [result],
        tmp_path / "reports" / "devices.csv",
    )

    with target.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert target.exists()
    assert len(rows) == 1
    assert rows[0]["device"] == "R1"
    assert rows[0]["host"] == "192.0.2.11"
    assert rows[0]["tags"] == "core,ospf"
    assert rows[0]["summary_status"] == "success"

    sections = json.loads(rows[0]["sections_json"])
    assert sections["system"]["data"]["os"] == "RouterOS"

    content = target.read_text(encoding="utf-8-sig")
    assert "credential_ref" not in content
    assert "raw output" not in content

def test_verification_data_is_safe_copy():
    result = TaskResult(
        device="R1",
        action="collect",
        success=True,
        message="Đã đọc dữ liệu thiết bị",
        data={
            "platform": "mikrotik",
            "connection_status": "online",
            "collected_at": "2026-11-09T10:00:00+00:00",
            "summary": {
                "status": "success",
            },
            "sections": {
                "interfaces": {
                    "status": "success",
                    "data": [
                        {
                            "name": "ether1",
                            "state": "up",
                        },
                    ],
                    "error_code": None,
                },
                "routes": {
                    "status": "success",
                    "data": [],
                    "error_code": None,
                },
                "ospf": {
                    "status": "success",
                    "data": [],
                    "error_code": None,
                },
            },
        },
    )

    verification = Collector.get_verification_data(result)

    assert verification["device"] == "R1"
    assert verification["platform"] == "mikrotik"
    assert verification["connection_status"] == "online"
    assert verification["summary_status"] == "success"
    assert verification["interfaces"]["data"][0]["state"] == "up"
    assert verification["routes"]["status"] == "success"
    assert verification["ospf"]["status"] == "success"

    verification["interfaces"]["data"][0]["state"] = "down"

    original_state = (
        result.data["sections"]["interfaces"]["data"][0]["state"]
    )
    assert original_state == "up"

def test_four_device_collection_isolates_offline_router(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    mikrotik_outputs = {
        "/system resource print": """
            version: 7.16.2
            uptime: 1d
            cpu: QEMU
            cpu-count: 1
            cpu-load: 5%
            total-memory: 128.0MiB
            free-memory: 64.0MiB
        """,
        "/system routerboard print": """
            routerboard: yes
            serial-number: ABCD1234
        """,
        "/interface print terse without-paging": "",
        "/ip route print terse without-paging": "",
        "/ip arp print terse without-paging": "",
        "/interface bridge host print terse without-paging": "",
        "/ip neighbor print terse without-paging": "",
        "/routing ospf neighbor print terse without-paging": "",
    }

    frr_outputs = {
        "show version": "FRRouting 8.2.2",
        "show interface json": "{}",
        "show ip route json": "{}",
        "show ip ospf neighbor json": "[]",
    }

    infos = [
        DeviceInfo("R1", "192.0.2.11", "mikrotik"),
        DeviceInfo("R2", "192.0.2.12", "mikrotik"),
        DeviceInfo("R3", "192.0.2.13", "frr"),
        DeviceInfo("R4", "192.0.2.14", "frr"),
    ]

    class InventoryDevice(ScriptedDevice):
        def connect(self):
            if self.info.name == "R2":
                raise DeviceConnectionError(
                    "Mô phỏng thiết bị offline"
                )

            super().connect()

    def fake_create(info, demo=False):
        outputs = (
            mikrotik_outputs
            if info.platform == "mikrotik"
            else frr_outputs
        )
        return InventoryDevice(info, outputs)

    monkeypatch.setattr(
        "services.connection_manager.DeviceFactory.create",
        fake_create,
    )

    manager = ConnectionManager(
        max_workers=4,
        demo=True,
    )
    collector = Collector()

    results = manager.run(
        infos,
        operation=collector.collect,
    )

    assert [result.device for result in results] == [
        "R1",
        "R2",
        "R3",
        "R4",
    ]

    failed = results[1]
    assert failed.success is False
    assert failed.data["connection_status"] == "offline"
    assert failed.error_code == "DeviceConnectionError"

    successful = [
        result
        for result in results
        if result.device != "R2"
    ]
    assert all(result.success for result in successful)

    assert results[0].data["summary"]["status"] == "success"
    assert results[2].data["summary"]["status"] == "partial"
    assert results[3].data["summary"]["status"] == "partial"

def test_exports_redact_nested_secrets_without_changing_source(tmp_path):
    sections = {"interfaces": {
        "status": "success", "error_code": None,
        "data": [{
            "name": "ether1",
            "comment": 'password="demo secret value"',
            "nested": {
                "private_key": "key-material",
                "credential_ref": "private-lab",
                "values": ["token=hidden-value", "normal description"],
            },
        }],
    }}
    original = deepcopy(sections)
    result = TaskResult("R1", "collect", True, "OK", data={"sections": sections})
    json_path = Collector.export_json([result], tmp_path / "report.json")
    csv_path = Collector.export_csv([result], tmp_path / "report.csv")
    json_sections = json.loads(json_path.read_text(encoding="utf-8"))[0]["sections"]
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        csv_sections = json.loads(next(csv.DictReader(file))["sections_json"])
    assert json_sections == csv_sections
    record = json_sections["interfaces"]["data"][0]
    assert record["name"] == "ether1"
    assert record["comment"] == "[REDACTED]"
    assert record["nested"]["values"] == ["[REDACTED]", "normal description"]
    for path in (json_path, csv_path):
        content = path.read_text(encoding="utf-8-sig")
        for secret in ("demo secret value", "key-material", "private-lab", "hidden-value"):
            assert secret not in content
    assert sections == original
    report = Collector._build_report_record(result)
    report["sections"]["interfaces"]["data"][0]["name"] = "changed"
    assert sections == original
