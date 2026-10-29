"""Giao dien nghiep vu de nhom thoa thuan; TV3-TV5 tu implement."""
from typing import Dict, List, Optional, Protocol, Sequence, Any
from core.base import NetworkDevice
from core.models import ConfigSnapshot, DeviceInfo, TaskResult


class InventoryService(Protocol):  # TV3
    def list_devices(self, group: Optional[str] = None,
                     role: Optional[str] = None,
                     tag: Optional[str] = None) -> List[DeviceInfo]: ...


class CollectorService(Protocol):  # TV3
    def collect(self, device: NetworkDevice) -> TaskResult: ...


class BackupService(Protocol):  # TV4
    def backup(self, device: NetworkDevice) -> TaskResult: ...
    def list_snapshots(self, device_name: str) -> List[ConfigSnapshot]: ...
    def diff(self, left: ConfigSnapshot, right: ConfigSnapshot) -> str: ...


class RestoreService(Protocol):  # TV5
    def restore(self, device: NetworkDevice, snapshot: ConfigSnapshot) -> TaskResult: ...


class ConfigService(Protocol):  # TV5
    def dry_run(self, devices: Sequence[NetworkDevice], template_name: str,
                variables: Dict[str, Any]) -> List[TaskResult]: ...
    def deploy(self, devices: Sequence[NetworkDevice], template_name: str,
               variables: Dict[str, Any]) -> List[TaskResult]: ...
