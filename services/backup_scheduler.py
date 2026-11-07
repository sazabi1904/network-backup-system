from threading import Event
from typing import Callable
from os import getenv
from services.logger import AuditLogger


class BackupScheduler:
    """Chạy một hàm backup theo chu kỳ."""

    def __init__(
        self,
        backup_job: Callable[[], None],
        interval_seconds: int = 300,
    ) -> None:
        if not callable(backup_job):
            raise TypeError("backup_job phải là một hàm")

        if type(interval_seconds) is not int or interval_seconds <= 0:
            raise ValueError("Chu kỳ phải là số nguyên dương")

        self.backup_job = backup_job
        self.interval_seconds = interval_seconds
        self._stop_event = Event()
        self.logger = AuditLogger()
        self.operator = getenv("APP_OPERATOR", "tv3")

    def run(self) -> None:
        """Chạy ngay, rồi chờ theo chu kỳ giữa các đợt."""
        self._stop_event.clear()

        try:
            while not self._stop_event.is_set():
                try:
                    self.backup_job()
                except Exception as exc:
                    try:
                        self.logger.log(
                            operator=self.operator,
                            device="scheduler",
                            action="scheduled_backup",
                            success=False,
                            error_code=type(exc).__name__,
                        )
                    except OSError:
                        raise RuntimeError(
                            "Không ghi được nhật ký scheduler"
                        ) from None

                self._stop_event.wait(self.interval_seconds)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Yêu cầu dừng lịch backup."""
        self._stop_event.set()