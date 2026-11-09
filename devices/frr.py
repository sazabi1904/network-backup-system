"""Platform-specific entry point for the shared read-only SSH adapter."""
from devices.ssh_adapter import SSHAdapter


class FRRDevice(SSHAdapter):
    def __init__(self, info, **kwargs):
        if info.platform != 'frr':
            raise ValueError('Expected frr DeviceInfo')
        super().__init__(info, **kwargs)
