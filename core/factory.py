"""Factory chi import adapter khi TV2 dang ky, khong ep TV2 xong truoc."""
from typing import Callable, Dict
from core.base import NetworkDevice
from core.fake_device import FakeDevice
from core.models import DeviceInfo


class DeviceFactory:
    _registry: Dict[str, Callable[[DeviceInfo], NetworkDevice]] = {}

    @classmethod
    def register(cls, platform: str, builder: Callable[[DeviceInfo], NetworkDevice]) -> None:
        if not callable(builder):
            raise TypeError("builder phai goi duoc")
        cls._registry[platform.strip().lower()] = builder

    @classmethod
    def create(cls, info: DeviceInfo, demo: bool = False) -> NetworkDevice:
        if demo:
            return FakeDevice(info)
        builder = cls._registry.get(info.platform.lower())
        if builder is None:
            raise ValueError(
                f"Chua dang ky adapter cho platform={info.platform!r}. "
                "TV2 can register('mikrotik'/'frr', lop_adapter)."
            )
        device = builder(info)
        if not isinstance(device, NetworkDevice):
            raise TypeError("Adapter phai ke thua NetworkDevice")
        return device
