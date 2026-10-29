"""Hop dong chung giua TV1 va TV2/TV3/TV4/TV5."""
from abc import ABC, abstractmethod
from typing import List
from core.models import DeviceInfo


class NetworkDevice(ABC):
    def __init__(self, info: DeviceInfo) -> None:
        self.info = info

    @abstractmethod
    def connect(self) -> None:
        """Ket noi; phat sinh loi neu that bai."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_command(self, command: str) -> str:
        """Gui lenh read-only va tra ve output."""
        raise NotImplementedError

    @abstractmethod
    def get_running_config(self) -> str:
        """Tra ve cau hinh trong pham vi nen tang ho tro."""
        raise NotImplementedError

    @abstractmethod
    def push_config(self, commands: List[str]) -> str:
        """Thuc thi cac lenh thay doi; tra ve output khong chua bi mat."""
        raise NotImplementedError

    @abstractmethod
    def restore_config(self, backup: str) -> bool:
        """Hoan tac pham vi duoc ho tro, tra ve True neu da xac minh."""
        raise NotImplementedError
