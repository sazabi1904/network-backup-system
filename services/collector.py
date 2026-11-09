from core.base import NetworkDevice
from core.models import TaskResult

from core.exceptions import UnsupportedFeatureError

from datetime import datetime, timezone
from pathlib import Path

import json
import csv
from copy import deepcopy



class Collector:
    """Thu thập và chuẩn hóa thông tin thiết bị."""

    SECTIONS = (
        "system",
        "serial",
        "interfaces",
        "routes",
        "arp",
        "mac_table",
        "discovery",
        "ospf",
    )


    COMMANDS = {
        "mikrotik": {
            "system": "/system resource print",
            "serial": "/system routerboard print",
            "interfaces": "/interface print terse without-paging",
            "routes": "/ip route print terse without-paging",
            "arp": "/ip arp print terse without-paging",
            "mac_table": "/interface bridge host print terse without-paging",
            "discovery": "/ip neighbor print terse without-paging",
            "ospf": "/routing ospf neighbor print terse without-paging",
        },
        "frr": {
            "system": "show version",
            "serial": None,
            "interfaces": "show interface json",
            "routes": "show ip route json",
            "arp": None,
            "mac_table": None,
            "discovery": None,
            "ospf": "show ip ospf neighbor json",
        },
    }


    @staticmethod
    def _parse_json_output(output: str) -> dict | list:
        """Đọc JSON dạng đối tượng hoặc danh sách."""
        if not isinstance(output, str):
            raise TypeError("Đầu ra phải là chuỗi")

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            raise ValueError("Đầu ra JSON không hợp lệ") from None

        if not isinstance(parsed, (dict, list)):
            raise ValueError(
                "JSON phải là đối tượng hoặc danh sách"
            )

        return parsed

    @classmethod
    def _normalize_json_section(cls, raw: dict) -> dict:
        """Đọc JSON của một mục đã thu thập."""
        if raw["status"] != "success":
            return {
                "status": raw["status"],
                "data": None,
                "error_code": raw["error_code"],
            }

        try:
            parsed = cls._parse_json_output(raw["data"])
        except (TypeError, ValueError) as exc:
            return {
                "status": "error",
                "data": None,
                "error_code": type(exc).__name__,
            }

        return {
            "status": "success",
            "data": parsed,
            "error_code": None,
        }

    @classmethod
    def _normalize_frr_sections(
        cls,
        system: dict,
        raw_sections: dict,
    ) -> dict:
        """Tập hợp các mục thu thập từ FRR."""
        normalized = {}

        for name in cls.SECTIONS:
            if name == "system":
                normalized[name] = dict(system)

            elif name in ("interfaces", "routes", "ospf"):
                normalized[name] = cls._normalize_json_section(
                    raw_sections[name]
                )

            else:
                raw = raw_sections[name]
                normalized[name] = {
                    "status": raw["status"],
                    "data": (
                        raw["data"]
                        if raw["status"] == "success"
                        else None
                    ),
                    "error_code": raw["error_code"],
                }

        return normalized

    @staticmethod
    def _split_routeros_line(line: str) -> list[str]:
        """Tách một dòng RouterOS, giữ khoảng trắng trong dấu nháy."""
        if not isinstance(line, str):
            raise TypeError("Dòng RouterOS phải là chuỗi")

        tokens = []
        current = []
        quoted = False
        escaped = False

        for character in line:
            if escaped:
                current.append("\\")
                current.append(character)
                escaped = False

            elif character == "\\":
                escaped = True

            elif character == '"':
                quoted = not quoted

            elif character.isspace() and not quoted:
                if current:
                    tokens.append("".join(current))
                    current = []

            else:
                current.append(character)

        if escaped:
            current.append("\\")

        if quoted:
            raise ValueError("Dấu nháy RouterOS chưa được đóng")

        if current:
            tokens.append("".join(current))

        return tokens

    @classmethod
    def _parse_routeros_terse(
        cls,
        output: str,
    ) -> list[dict]:
        """Chuyển bảng RouterOS terse thành danh sách bản ghi."""
        if not isinstance(output, str):
            raise TypeError("Đầu ra phải là chuỗi")

        records = []

        for source_line in output.splitlines():
            line = source_line.strip()

            if not line:
                continue

            lowered = line.lower()

            if lowered.startswith(("flags:", ";;;")):
                continue

            if lowered.startswith(
                (
                    "failure:",
                    "bad command name",
                    "syntax error",
                )
            ):
                raise ValueError(
                    "RouterOS trả về thông báo lỗi"
                )

            tokens = cls._split_routeros_line(line)
            record = {}
            flags = []
            has_property = False

            for token in tokens:
                if (
                    token.isdigit()
                    and "index" not in record
                ):
                    record["index"] = int(token)

                elif "=" in token:
                    key, value = token.split("=", 1)
                    key = (
                        key.strip()
                        .lstrip(".")
                        .replace("-", "_")
                    )

                    if key:
                        record[key] = value
                        has_property = True

                else:
                    flags.append(token)

            if not has_property:
                raise ValueError(
                    "Không nhận diện được bản ghi RouterOS"
                )

            record["flags"] = flags
            records.append(record)

        return records

    @classmethod
    def _normalize_routeros_terse_section(
        cls,
        raw: dict,
    ) -> dict:
        """Chuyển RouterOS terse thành danh sách bản ghi."""
        if raw["status"] != "success":
            return {
                "status": raw["status"],
                "data": None,
                "error_code": raw["error_code"],
            }

        try:
            records = cls._parse_routeros_terse(
                raw["data"]
            )
        except (TypeError, ValueError) as exc:
            return {
                "status": "error",
                "data": None,
                "error_code": type(exc).__name__,
            }

        return {
            "status": "success",
            "data": records,
            "error_code": None,
        }
    
    @staticmethod
    def _parse_key_values(output: str) -> dict[str, str]:
        """Tách đầu ra dạng khóa: giá trị."""
        if not isinstance(output, str):
            raise TypeError("Đầu ra phải là chuỗi")

        parsed = {}

        for line in output.splitlines():
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().replace("-", "_")

            if key:
                parsed[key] = value.strip()

        if not parsed:
            raise ValueError("Không tìm thấy dữ liệu dạng khóa: giá trị")

        return parsed

    @classmethod
    def _normalize_mikrotik_system(cls, output: str) -> dict:
        """Chuẩn hóa các trường từ /system resource print."""
        raw = cls._parse_key_values(output)

        sources = {
            "version": "version",
            "uptime": "uptime",
            "cpu": "cpu",
            "cpu_count": "cpu_count",
            "cpu_load": "cpu_load",
            "memory_total": "total_memory",
            "memory_free": "free_memory",
        }

        values = {
            field: raw.get(source) or None
            for field, source in sources.items()
        }

        if not any(value is not None for value in values.values()):
            raise ValueError("Không nhận diện được dữ liệu hệ thống MikroTik")

        values = {"os": "RouterOS", **values}

        return {
            field: {
                "status": "success" if value is not None else "unavailable",
                "data": value,
                "error_code": None,
            }
            for field, value in values.items()
        }

    @classmethod
    def _normalize_mikrotik_serial(
        cls,
        raw: dict,
    ) -> dict:
        """Đọc serial nếu thiết bị cung cấp RouterBOARD."""
        if raw["status"] != "success":
            return {
                "status": raw["status"],
                "data": None,
                "error_code": raw["error_code"],
            }

        try:
            fields = cls._parse_key_values(raw["data"])

            known_fields = {
                "routerboard",
                "serial_number",
            }

            if not known_fields.intersection(fields):
                raise ValueError(
                    "Không nhận diện được dữ liệu RouterBOARD"
                )

            serial = fields.get("serial_number")

            if serial:
                return {
                    "status": "success",
                    "data": serial,
                    "error_code": None,
                }

            if fields.get("routerboard", "").lower() == "no":
                return {
                    "status": "unsupported",
                    "data": None,
                    "error_code": "UnsupportedFeatureError",
                }

            return {
                "status": "unavailable",
                "data": None,
                "error_code": None,
            }

        except (TypeError, ValueError) as exc:
            return {
                "status": "error",
                "data": None,
                "error_code": type(exc).__name__,
            }

    @classmethod
    def _normalize_mikrotik_sections(
        cls,
        system: dict,
        raw_sections: dict,
    ) -> dict:
        """Tập hợp các mục thu thập từ MikroTik."""
        normalized = {}

        for name in cls.SECTIONS:
            if name == "system":
                normalized[name] = dict(system)

            elif name == "serial":
                normalized[name] = (
                    cls._normalize_mikrotik_serial(
                        raw_sections[name]
                    )
                )

            else:
                normalized[name] = (
                    cls._normalize_routeros_terse_section(
                        raw_sections[name]
                    )
                )

        return normalized    

    @staticmethod
    def _normalize_frr_system(output: str) -> dict:
        """Chuẩn hóa phiên bản từ lệnh show version của FRR."""
        if not isinstance(output, str):
            raise TypeError("Đầu ra phải là chuỗi")

        header = next(
            (
                line.strip()
                for line in output.splitlines()
                if line.strip()
            ),
            "",
        )
        parts = header.split()

        if len(parts) < 2 or parts[0] != "FRRouting":
            raise ValueError("Không nhận diện được phiên bản FRRouting")

        result = {
            "os": {
                "status": "success",
                "data": "FRRouting",
                "error_code": None,
            },
            "version": {
                "status": "success",
                "data": parts[1],
                "error_code": None,
            },
        }

        for field in (
            "uptime",
            "cpu",
            "cpu_count",
            "cpu_load",
            "memory_total",
            "memory_free",
        ):
            result[field] = {
                "status": "unsupported",
                "data": None,
                "error_code": "UnsupportedFeatureError",
            }

        return result

    @classmethod
    def _normalize_system(cls, platform: str, output: str) -> dict:
        """Chọn bộ chuẩn hóa theo nền tảng."""
        try:
            if platform == "mikrotik":
                fields = cls._normalize_mikrotik_system(output)
            elif platform == "frr":
                fields = cls._normalize_frr_system(output)
            else:
                raise UnsupportedFeatureError(
                    "Nền tảng chưa được hỗ trợ"
                )

        except UnsupportedFeatureError as exc:
            return {
                "status": "unsupported",
                "data": None,
                "error_code": type(exc).__name__,
            }

        except (TypeError, ValueError) as exc:
            return {
                "status": "error",
                "data": None,
                "error_code": type(exc).__name__,
            }

        complete = all(
            field["status"] == "success"
            for field in fields.values()
        )

        return {
            "status": "success" if complete else "partial",
            "data": fields,
            "error_code": None,
        }

    @classmethod
    def _normalize_sections(
        cls,
        platform: str,
        system: dict,
        raw_sections: dict,
    ) -> dict:
        """Chọn bộ xử lý các mục theo nền tảng."""
        if platform == "mikrotik":
            return cls._normalize_mikrotik_sections(
                system,
                raw_sections,
            )

        if platform == "frr":
            return cls._normalize_frr_sections(
                system,
                raw_sections,
            )

        return {
            name: {
                "status": "unsupported",
                "data": None,
                "error_code": "UnsupportedFeatureError",
            }
            for name in cls.SECTIONS
        }

    

    @classmethod
    def _summarize_normalized_sections(
        cls,
        sections: dict,
    ) -> dict:
        """Tổng hợp kết quả từ các mục đã xử lý."""
        items = [
            sections[name]
            for name in cls.SECTIONS
        ]

        if all(
            item["status"] == "success"
            for item in items
        ):
            return {
                "status": "success",
                "success": True,
                "error_code": None,
            }

        if any(
            item["status"] in ("success", "partial")
            for item in items
        ):
            return {
                "status": "partial",
                "success": True,
                "error_code": None,
            }

        for item in items:
            if item["status"] == "error":
                return {
                    "status": "error",
                    "success": False,
                    "error_code": item["error_code"],
                }

        return {
            "status": "unsupported",
            "success": False,
            "error_code": "UnsupportedFeatureError",
        }

    @staticmethod
    def _build_report_record(
        result: TaskResult,
    ) -> dict:
        """Tạo bản ghi báo cáo từ một TaskResult."""
        if not isinstance(result, TaskResult):
            raise TypeError("Kết quả phải là TaskResult")

        data = result.data

        if not isinstance(data, dict):
            raise TypeError("TaskResult.data phải là dict")

        device_info = data.get("device_info", {})
        if not isinstance(device_info, dict):
            device_info = {}

        summary = data.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}

        tags = device_info.get("tags", [])
        if isinstance(tags, (list, tuple)):
            tags = [str(tag) for tag in tags]
        else:
            tags = []

        return {
            "device": result.device,
            "host": device_info.get("host"),
            "platform": (
                data.get("platform")
                or device_info.get("platform")
            ),
            "port": device_info.get("port"),
            "group": device_info.get("group"),
            "role": device_info.get("role"),
            "tags": tags,
            "action": result.action,
            "connection_status": data.get(
                "connection_status"
            ),
            "collected_at": data.get("collected_at"),
            "success": result.success,
            "summary_status": summary.get("status"),
            "message": result.message,
            "error_code": result.error_code,
            "sections": data.get("sections"),
        }

    @classmethod
    def export_json(
        cls,
        results: list[TaskResult],
        path: str | Path,
    ) -> Path:
        """Xuất danh sách kết quả thu thập ra JSON."""
        if not isinstance(results, list):
            raise TypeError("results phải là danh sách")

        if any(
            not isinstance(result, TaskResult)
            for result in results
        ):
            raise TypeError(
                "results phải chứa các TaskResult"
            )

        target = Path(path)

        if target.suffix.lower() != ".json":
            raise ValueError(
                "File báo cáo JSON phải có đuôi .json"
            )

        records = [
            cls._build_report_record(result)
            for result in results
        ]

        content = json.dumps(
            records,
            ensure_ascii=False,
            indent=2,
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        target.write_text(
            content,
            encoding="utf-8",
        )

        return target

    @classmethod
    def export_csv(
        cls,
        results: list[TaskResult],
        path: str | Path,
    ) -> Path:
        """Xuất danh sách kết quả thu thập ra CSV."""
        if not isinstance(results, list):
            raise TypeError("results phải là danh sách")

        if any(
            not isinstance(result, TaskResult)
            for result in results
        ):
            raise TypeError(
                "results phải chứa các TaskResult"
            )

        target = Path(path)

        if target.suffix.lower() != ".csv":
            raise ValueError(
                "File báo cáo CSV phải có đuôi .csv"
            )
        fieldnames = [
            "device",
            "host",
            "platform",
            "port",
            "group",
            "role",
            "tags",
            "action",
            "connection_status",
            "collected_at",
            "success",
            "summary_status",
            "message",
            "error_code",
            "sections_json",
        ]
        rows = []

        for result in results:
            record = cls._build_report_record(result)

            rows.append({
                "device": record["device"],
                "host": record["host"],
                "platform": record["platform"],
                "port": record["port"],
                "group": record["group"],
                "role": record["role"],
                "tags": ",".join(record["tags"]),
                "action": record["action"],
                "connection_status": record["connection_status"],
                "collected_at": record["collected_at"],
                "success": record["success"],
                "summary_status": record["summary_status"],
                "message": record["message"],
                "error_code": record["error_code"],
                "sections_json": json.dumps(
                    record["sections"] or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            })

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with target.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(rows)

        return target

    @staticmethod
    def get_verification_data(
        result: TaskResult,
    ) -> dict:
        """Lấy dữ liệu interface, route và OSPF để xác minh."""
        if not isinstance(result, TaskResult):
            raise TypeError("result phải là TaskResult")

        if not isinstance(result.data, dict):
            raise ValueError(
                "TaskResult không chứa dữ liệu hợp lệ"
            )

        sections = result.data.get("sections")

        if not isinstance(sections, dict):
            sections = {}

        def read_section(name: str) -> dict:
            section = sections.get(name)

            if not isinstance(section, dict):
                return {
                    "status": "unavailable",
                    "data": None,
                    "error_code": None,
                }

            return deepcopy(section)

        summary = result.data.get("summary")
        summary_status = None

        if isinstance(summary, dict):
            summary_status = summary.get("status")

        return {
            "device": result.device,
            "platform": result.data.get("platform"),
            "connection_status": result.data.get(
                "connection_status"
            ),
            "collected_at": result.data.get("collected_at"),
            "summary_status": summary_status,
            "interfaces": read_section("interfaces"),
            "routes": read_section("routes"),
            "ospf": read_section("ospf"),
        }

    def _collect_raw_sections(self, device: NetworkDevice) -> dict:
        """Đọc từng mục độc lập trên thiết bị đã kết nối."""
        profile = self.COMMANDS.get(device.info.platform)
        sections = {}

        for section in self.SECTIONS:
            command = profile[section] if profile is not None else None

            if command is None:
                sections[section] = {
                    "status": "unsupported",
                    "data": None,
                    "error_code": "UnsupportedFeatureError",
                }
            else:
                sections[section] = self._read_command(
                    device,
                    command,
                )

        return sections

    def collect(self, device: NetworkDevice) -> TaskResult:
        """Thu thập thông tin hệ thống trên thiết bị đã kết nối."""
        platform = device.info.platform
        profile = self.COMMANDS.get(platform, {})
        raw_sections = self._collect_raw_sections(device)
        raw = raw_sections["system"]

        if raw["status"] == "success":
            system = self._normalize_system(platform, raw["data"])
        else:
            system = {
                "status": raw["status"],
                "data": None,
                "error_code": raw["error_code"],
            }

        sections = self._normalize_sections(
            platform,
            system,
            raw_sections,
        )
        summary = self._summarize_normalized_sections(
            sections
        )
        status = summary["status"]

        messages = {
            "success": "Đã đọc dữ liệu thiết bị",
            "partial": "Đã đọc được một phần dữ liệu thiết bị",
            "unsupported": "Không hỗ trợ thu thập dữ liệu thiết bị",
            "error": "Không thu thập được dữ liệu thiết bị",
        }

        return TaskResult(
            device=device.info.name,
            action="collect",
            success=summary["success"],
            message=messages[status],

            data={
                "platform": platform,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "commands": [
                    profile[section]
                    for section in self.SECTIONS
                    if profile.get(section) is not None
                ],
                "raw_sections": raw_sections,
                "system_raw": raw,
                "system": system,
                "summary": summary,
                "sections": sections,
            },
            error_code=summary["error_code"],
        )

    @staticmethod
    def _read_command(device: NetworkDevice, command: str) -> dict:
        """Đọc một lệnh và ghi nhận kết quả riêng."""
        try:
            output = device.send_command(command)

            if not isinstance(output, str):
                raise TypeError("Kết quả lệnh phải là chuỗi")

        except UnsupportedFeatureError:
            return {
                "status": "unsupported",
                "data": None,
                "error_code": "UnsupportedFeatureError",
            }

        except Exception as exc:
            return {
                "status": "error",
                "data": None,
                "error_code": type(exc).__name__,
            }

        return {
            "status": "success",
            "data": output,
            "error_code": None,
        }