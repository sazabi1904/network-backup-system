"""Models dung chung. Cac TV khong duoc tu y thay doi chu ky API."""
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    host: str
    platform: str
    port: int = 22
    group: str = "lab"
    role: str = "router"
    tags: Tuple[str, ...] = ()
    credential_ref: str = "lab"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DeviceInfo":
        name = str(raw["name"]).strip()
        host = str(raw["host"]).strip()
        platform = str(raw["platform"]).strip().lower()
        port = int(raw.get("port", 22))
        if not name or not host or not platform or not 1 <= port <= 65535:
            raise ValueError("Thong tin thiet bi khong hop le")
        tags = raw.get("tags", [])
        if not isinstance(tags, (list, tuple)):
            raise ValueError("tags phai la danh sach")
        return cls(
            name=name, host=host, platform=platform, port=port,
            group=str(raw.get("group", "lab")),
            role=str(raw.get("role", "router")),
            tags=tuple(str(t) for t in tags),
            credential_ref=str(raw.get("credential_ref", "lab")),
        )


@dataclass(frozen=True)
class ConfigSnapshot:
    snapshot_id: str
    device_name: str
    platform: str
    captured_at: str  # ISO 8601, co timezone
    content: str
    sha256: str
    scope: str = "device-supported-config"


@dataclass
class TaskResult:
    device: str
    action: str
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
