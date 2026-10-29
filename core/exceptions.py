"""Nhom ngoai le thong nhat cho cac module."""


class NetworkAutomationError(Exception):
    """Loi chung cua ung dung."""


class DeviceConnectionError(NetworkAutomationError):
    """Khong the ket noi thiet bi."""


class DeviceAuthenticationError(DeviceConnectionError):
    """Dang nhap thiet bi that bai."""


class DeviceTimeoutError(DeviceConnectionError):
    """Thiet bi khong phan hoi trong thoi gian cho."""


class DeviceCommandError(NetworkAutomationError):
    """Lenh thuc thi loi."""


class DeviceRestoreError(NetworkAutomationError):
    """Khong khoi phuc duoc cau hinh."""


class UnsupportedFeatureError(NetworkAutomationError):
    """Thiet bi khong ho tro tinh nang."""
