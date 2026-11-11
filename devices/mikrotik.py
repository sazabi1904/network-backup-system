"""Platform-specific entry point for the shared read-only SSH adapter."""
from devices.ssh_adapter import SSHAdapter


class MikroTikDevice(SSHAdapter):
    def __init__(self, info, **kwargs):
        if info.platform != 'mikrotik':
            raise ValueError('Expected mikrotik DeviceInfo')
        super().__init__(info, **kwargs)
