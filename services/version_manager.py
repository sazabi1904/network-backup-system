
from typing import List, Optional

from core.models import ConfigSnapshot
from services.backup_manager import BackupManager


class VersionManager:
    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager

    def list_versions(
        self, device_name: str
    ) -> List[ConfigSnapshot]:
        """Lay danh sach phien ban cua thiet bi."""
        return self.backup_manager.list_snapshots(
            device_name
        )

    def latest_version(
        self, device_name: str
    ) -> Optional[ConfigSnapshot]:
        """Lay phien ban moi nhat."""
        versions = self.list_versions(device_name)

        if not versions:
            return None

        return versions[0]

    def get_version(
        self, device_name: str, snapshot_id: str
    ) -> ConfigSnapshot:
        """Tim phien ban theo ID."""
        versions = self.list_versions(device_name)

        for version in versions:
            if version.snapshot_id == snapshot_id:
                return version

        raise ValueError(
            f"Khong tim thay phien ban: {snapshot_id}"
        )
