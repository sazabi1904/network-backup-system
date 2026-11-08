
import time

from core.models import TaskResult
from services.backup_manager import BackupManager


class BackupScheduler:
    def __init__(
        self,
        backup_manager: BackupManager,
        interval_seconds: int = 300
    ):
        if interval_seconds <= 0:
            raise ValueError("Khoang thoi gian phai > 0")

        self.backup_manager = backup_manager
        self.interval_seconds = interval_seconds
        self.next_run = time.monotonic()

    def run_once(self, devices):
        """Backup mot lan cho danh sach thiet bi."""
        results = []

        for device in devices:
            result = None

            try:
                device.connect()

                result = self.backup_manager.backup(
                    device
                )

            except Exception as error:
                result = TaskResult(
                    device=device.info.name,
                    action="backup",
                    success=False,
                    message="Backup that bai",
                    error_code=type(error).__name__
                )

            finally:
                try:
                    device.disconnect()
                except Exception as error:
                    if result.success:
                        result.success = False
                        result.message = (
                            "Da backup nhung ngat ket noi loi"
                        )
                        result.error_code = (
                            type(error).__name__
                        )

            results.append(result)

        return results

    def run_pending(self, devices):
        """Chi backup khi den thoi gian da dat."""
        now = time.monotonic()

        if now < self.next_run:
            return []

        self.next_run = (
            now + self.interval_seconds
        )

        return self.run_once(devices)
    