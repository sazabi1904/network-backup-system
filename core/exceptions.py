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


class DeviceWriteError(DeviceCommandError):
    """Sanitized write failure. True means remote state must be read again."""
    def __init__(self, code, may_have_applied=True):
        self.code = code
        self.may_have_applied = may_have_applied
        super().__init__(code + '; verify device state before retrying')
