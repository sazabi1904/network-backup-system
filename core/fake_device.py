"""Fake device chi de unit test. KHONG mo phong cu phap Cisco/MikroTik/FRR."""
from typing import List, Optional
from core.base import NetworkDevice
from core.exceptions import (
    DeviceCommandError, DeviceConnectionError, DeviceRestoreError
)
from core.models import DeviceInfo


class FakeDevice(NetworkDevice):
    def __init__(
        self,
        info: DeviceInfo,
        initial_config: Optional[str] = None,
        fail_connect: bool = False,
        fail_push: bool = False,
        fail_restore: bool = False,
    ) -> None:
        super().__init__(info)
        self._connected = False
        self._config = initial_config if initial_config is not None else f"hostname {info.name}\n"
        self.fail_connect = fail_connect
        self.fail_push = fail_push
        self.fail_restore = fail_restore

    def _require_connection(self) -> None:
        if not self._connected:
            raise DeviceConnectionError(f"{self.info.name} chua ket noi")

    def connect(self) -> None:
        if self.fail_connect:
            raise DeviceConnectionError(f"{self.info.name} offline (gia lap)")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def send_command(self, command: str) -> str:
        self._require_connection()
        if not command.strip():
            raise DeviceCommandError("Lenh rong")
        if command.lower().strip() in ("show version", "/system resource print", "show version frr"):
            return f"{self.info.name} - FAKE OS - test only"
        return f"FAKE OUTPUT: {command}"

    def get_running_config(self) -> str:
        self._require_connection()
        return self._config

    def push_config(self, commands: List[str]) -> str:
        self._require_connection()
        if self.fail_push:
            raise DeviceCommandError("Gia lap: apply config that bai")
        if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
            raise ValueError("commands phai la List[str]")
        if commands:
            self._config = self._config.rstrip("\n") + "\n" + "\n".join(commands) + "\n"
        return "FAKE: applied"

    def restore_config(self, backup: str) -> bool:
        self._require_connection()
        if self.fail_restore:
            raise DeviceRestoreError("Gia lap: restore that bai")
        if not isinstance(backup, str):
            raise TypeError("backup phai la chuoi")
        self._config = backup
        return self._config == backup
