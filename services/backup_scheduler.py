
import time

from services.change_detector import ChangeDetector
from core.models import TaskResult
from services.backup_manager import BackupManager


class BackupScheduler:
    def __init__(
        self,
        backup_manager: BackupManager,
        interval_seconds: int = 300,
        detect_changes: bool = False,
        audit_logger=None,
        operator: str = "TV4",
    ):
        if interval_seconds <= 0:
            raise ValueError("Khoang thoi gian phai > 0")

        self.backup_manager = backup_manager
        self.interval_seconds = interval_seconds
        self.next_run = time.monotonic()
        self.change_detector = (
            ChangeDetector(backup_manager)
            if detect_changes
            else None
        )

        # AuditLogger tuy chon, khong anh huong code cu
        self.audit_logger = audit_logger
        self.operator = operator

    def _ghi_log(self, device, action, success, error_code=None):
        """Ghi audit log, khong de loi log dung backup."""
        if self.audit_logger is None:
            return

        try:
            self.audit_logger.log(
                operator=self.operator,
                device=device,
                action=action,
                success=success,
                error_code=error_code,
            )
        except Exception as exc:
            print(
                "[CANH BAO] Loi ghi AuditLogger:",
                type(exc).__name__,
            )

    def run_once(self, devices):
        """Kiem tra thay doi truoc backup neu duoc bat."""
        results = []

        for device in devices:
            result = None
            change_data = None
            backup_skipped = False

            try:
                device.connect()

                if self.change_detector is not None:
                    checked = self.change_detector.check(device)

                    if checked.success:
                        change_data = {
                            "status": (
                                "CHANGED"
                                if checked.data["changed"]
                                else "UNCHANGED"
                            ),
                            "baseline_snapshot_id": (
                                checked.data["snapshot_id"]
                            ),
                            "diff": checked.data["diff"],
                        }

                        self._ghi_log(
                            device.info.name,
                            (
                                "detect_change_changed"
                                if checked.data["changed"]
                                else "detect_change_unchanged"
                            ),
                            True,
                        )

                    elif checked.error_code == "NO_BASELINE":
                        # Router chua co backup: tao ban goc.
                        change_data = {"status": "NO_BASELINE"}

                        self._ghi_log(
                            device.info.name,
                            "detect_change",
                            False,
                            "NO_BASELINE",
                        )

                    else:
                        # Khong ghi de baseline khi kiem tra loi.
                        backup_skipped = True
                        result = TaskResult(
                            device=device.info.name,
                            action="backup",
                            success=False,
                            message=(
                                "Kiem tra thay doi that bai; "
                                "bo qua backup"
                            ),
                            error_code=(
                                checked.error_code
                                or "CHANGE_CHECK_FAILED"
                            ),
                        )

                        self._ghi_log(
                            device.info.name,
                            "detect_change",
                            False,
                            result.error_code,
                        )

                if result is None:
                    result = self.backup_manager.backup(device)

            except Exception as error:
                result = TaskResult(
                    device=device.info.name,
                    action="backup",
                    success=False,
                    message="Backup that bai",
                    error_code=type(error).__name__,
                )

            finally:
                try:
                    device.disconnect()
                except Exception as error:
                    if result is not None and result.success:
                        result.success = False
                        result.message = (
                            "Da backup nhung ngat ket noi loi"
                        )
                        result.error_code = type(error).__name__

            if result is not None and change_data is not None:
                if not isinstance(result.data, dict):
                    result.data = {}

                result.data["change_check"] = change_data

            # Ghi log ket qua backup cho tung router
            self._ghi_log(
                device.info.name,
                "backup_skipped" if backup_skipped else "backup",
                result.success,
                result.error_code,
            )

            results.append(result)

        return results

    def run_pending(self, devices):
        """Chi backup khi den thoi gian da dat."""
        now = time.monotonic()

        if now < self.next_run:
            return []

        try:
            return self.run_once(devices)
        finally:
            # Chi tinh chu ky moi sau khi luot backup ket thuc
            self.next_run = (
                time.monotonic() + self.interval_seconds
            )
