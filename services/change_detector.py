
import hashlib
import difflib
import re

from core.models import TaskResult
from services.backup_manager import BackupManager


class ChangeDetector:
    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager
    
    @staticmethod
    def _normalize_config(content: str, platform: str) -> str:
        """Bo qua timestamp export cua MikroTik khi so sanh."""

        if platform.lower() not in ("mikrotik", "routeros"):
            return content

        return "".join(
            line
            for line in content.splitlines(keepends=True)
            if not re.match(
                r"^#\s+\d{4}-\d{2}-\d{2}\s+"
                r"\d{2}:\d{2}:\d{2}\s+by RouterOS\b",
                line,
            )
        )

    def check(self, device) -> TaskResult:
        name = device.info.name

        try:
            # Lay danh sach cac ban backup
            snapshots = self.backup_manager.list_snapshots(name)

            if not snapshots:
                return TaskResult(
                    device=name,
                    action="detect_change",
                    success=False,
                    message="Chua co ban backup de so sanh",
                    error_code="NO_BASELINE"
                )

            # Chon ban backup moi nhat
            latest = snapshots[0]

            # Kiem tra dung nen tang
            if latest.platform != device.info.platform:
                return TaskResult(
                    device=name,
                    action="detect_change",
                    success=False,
                    message="Nen tang thiet bi khong khop backup",
                    error_code="PLATFORM_MISMATCH"
                )
            
            # Lay cau hinh hien tai
            current = device.get_running_config()

            # Chuan hoa de bo qua timestamp RouterOS
            baseline_normalized = self._normalize_config(
                latest.content,
                latest.platform,
            )

            current_normalized = self._normalize_config(
                current,
                device.info.platform,
            )

            # So sanh SHA-256 cua cau hinh da chuan hoa
            baseline_hash = hashlib.sha256(
                baseline_normalized.encode("utf-8")
            ).hexdigest()

            current_hash = hashlib.sha256(
                current_normalized.encode("utf-8")
            ).hexdigest()

            changed = current_hash != baseline_hash

            # Chi hien thi khac biet cau hinh thuc su
            diff = "".join(
                difflib.unified_diff(
                    baseline_normalized.splitlines(
                        keepends=True
                    ),
                    current_normalized.splitlines(
                        keepends=True
                    ),
                    fromfile="Backup",
                    tofile="Current",
                )
            )

            
            return TaskResult(
                device=name,
                action="detect_change",
                success=True,
                message=(
                    "Phat hien thay doi"
                    if changed
                    else "Khong co thay doi"
                ),
                data={
                    "changed": changed,
                    "snapshot_id": latest.snapshot_id,
                    "diff": diff
                }
            )

        except Exception as error:
            return TaskResult(
                device=name,
                action="detect_change",
                success=False,
                message="Khong the kiem tra cau hinh",
                error_code=type(error).__name__
            )
