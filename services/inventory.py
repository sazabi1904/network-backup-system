import json
import ipaddress
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from core.models import DeviceInfo
from dataclasses import asdict, replace
from tempfile import NamedTemporaryFile


class InventoryManager:
    """Quản lý danh sách thiết bị từ file JSON hoặc YAML."""

    def __init__(self, inventory_path: Union[str, Path]) -> None:
        self.path = Path(inventory_path)
        self._devices: Dict[str, DeviceInfo] = {}

    def load(self) -> List[DeviceInfo]:
        """Đọc và kiểm tra toàn bộ danh sách thiết bị."""
        suffix = self.path.suffix.lower()
        if suffix not in (".json", ".yaml", ".yml"):
            raise ValueError("Inventory phải là file JSON hoặc YAML")

        with self.path.open(encoding="utf-8-sig") as file:
            if suffix == ".json":
                data = json.load(file)
            else:
                data = yaml.safe_load(file)

        if not isinstance(data, list):
            raise ValueError("Inventory phải chứa một danh sách thiết bị")

        allowed_fields = {
            "name", "host", "platform", "port",
            "group", "role", "tags", "credential_ref",
        }
        loaded_devices: Dict[str, DeviceInfo] = {}

        for raw in data:
            if not isinstance(raw, dict):
                raise ValueError("Mỗi thiết bị phải là một đối tượng")

            if not set(raw).issubset(allowed_fields):
                raise ValueError("Thiết bị chứa trường không được hỗ trợ")

            for field in ("name", "host", "platform"):
                if not isinstance(raw.get(field), str) or not raw[field].strip():
                    raise ValueError("Thiếu hoặc sai name, host, platform")

            self._validate_ip(raw["host"])
            self._validate_port(raw.get("port", 22))
            info = DeviceInfo.from_mapping(raw)
            if info.name in loaded_devices:
                raise ValueError("Tên thiết bị bị trùng")

            loaded_devices[info.name] = info

        self._devices = loaded_devices
        return list(self._devices.values())

    def list_devices(
        self,
        group: Optional[str] = None,
        role: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[DeviceInfo]:
        """Liệt kê thiết bị thỏa mãn các điều kiện lọc."""
        results: List[DeviceInfo] = []

        for device in self._devices.values():
            if group is not None and device.group != group:
                continue

            if role is not None and device.role != role:
                continue

            if tag is not None and tag not in device.tags:
                continue

            results.append(device)

        return results

    def add_device(self, device: DeviceInfo) -> DeviceInfo:
        """Thêm một thiết bị mới vào Inventory trong bộ nhớ."""
        if not isinstance(device, DeviceInfo):
            raise TypeError("device phải là một DeviceInfo")

        raw = asdict(device)
        for field in ("name", "host", "platform"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise ValueError("Thiếu hoặc sai name, host, platform")

        self._validate_ip(raw["host"])
        self._validate_port(raw.get("port", 22))
        info = DeviceInfo.from_mapping(raw)
        if info.name in self._devices:
            raise ValueError("Tên thiết bị đã tồn tại")

        self._devices[info.name] = info
        return info

    def update_device(self, device_name: str, **changes) -> DeviceInfo:
        """Cập nhật các thuộc tính của một thiết bị trong bộ nhớ."""
        device_name = device_name.strip()
        if device_name not in self._devices:
            raise KeyError("Không tìm thấy thiết bị")

        candidate = replace(self._devices[device_name], **changes)
        raw = asdict(candidate)

        for field in ("name", "host", "platform"):
            if not isinstance(raw[field], str) or not raw[field].strip():
                raise ValueError("Thiếu hoặc sai name, host, platform")

        self._validate_ip(raw["host"])
        self._validate_port(raw.get("port", 22))
        info = DeviceInfo.from_mapping(raw)
        if info.name != device_name and info.name in self._devices:
            raise ValueError("Tên thiết bị đã tồn tại")

        if info.name != device_name:
            del self._devices[device_name]

        self._devices[info.name] = info
        return info

    def remove_device(self, device_name: str) -> DeviceInfo:
        """Xóa thiết bị theo tên khỏi Inventory trong bộ nhớ."""
        device_name = device_name.strip()
        if device_name not in self._devices:
            raise KeyError("Không tìm thấy thiết bị")

        return self._devices.pop(device_name)

    def save(self) -> None:
        """Lưu Inventory hiện tại xuống file JSON hoặc YAML."""
        suffix = self.path.suffix.lower()
        if suffix not in (".json", ".yaml", ".yml"):
            raise ValueError("Inventory phải là file JSON hoặc YAML")

        data = [asdict(device) for device in self._devices.values()]
        for raw in data:
            raw["tags"] = list(raw["tags"])

        if suffix == ".json":
            content = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            content = yaml.safe_dump(
                data, allow_unicode=True, sort_keys=False
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None

        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)

            temp_path.replace(self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_ip(host: str) -> None:
        """Kiểm tra IPv4/IPv6 theo cách chuẩn hóa host của DeviceInfo."""
        try:
            ipaddress.ip_address(host.strip())
        except ValueError:
            raise ValueError("Địa chỉ IP không hợp lệ") from None

    @staticmethod
    def _validate_port(port: int) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port phải là số nguyên từ 1 đến 65535")

    