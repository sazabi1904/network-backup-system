import re
from datetime import datetime, timezone
from pathlib import Path

from core.base import NetworkDevice
from core.models import ConfigSnapshot, TaskResult
from os import getenv
from services.logger import AuditLogger
from typing import Iterable, List, Optional
import json
from hashlib import sha256

class BackupManager:
    """Sao lưu cấu hình và quản lý lịch sử backup."""

    def __init__(self, backup_dir: str = "backups") -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.logger = AuditLogger()
        self.operator = getenv("APP_OPERATOR", "tv3")

    def backup(self, device: NetworkDevice) -> TaskResult:
        """Lưu cấu hình của một thiết bị đã kết nối."""
        try:
            content = device.get_running_config()

            if not isinstance(content, str) or not content.strip():
                raise ValueError("Cấu hình trống hoặc không hợp lệ")

            name = re.sub(r"[^A-Za-z0-9_-]", "_", device.info.name)
            captured_at = datetime.now(timezone.utc)
            timestamp = captured_at.strftime("%Y%m%dT%H%M%S_%fZ")
            path = self.backup_dir / f"{name}_{timestamp}.txt"

    

            with path.open("x", encoding="utf-8", newline="") as file:
                file.write(content)

            metadata = {
                "snapshot_id": path.stem,
                "device_name": device.info.name,
                "platform": device.info.platform,
                "captured_at": captured_at.isoformat(),
                "sha256": sha256(content.encode("utf-8")).hexdigest(),
                "scope": "device-supported-config",
            }

            metadata_path = path.with_suffix(".json")
            with metadata_path.open("x", encoding="utf-8") as file:
                json.dump(metadata, file, ensure_ascii=False, indent=2)

            result = TaskResult(
                device=device.info.name,
                action="backup",
                success=True,
                message="Sao lưu thành công",
                data={
                    "path": str(path),
                    "metadata_path": str(metadata_path),
                },
            )
        except Exception as exc:
            result = TaskResult(
                device=device.info.name,
                action="backup",
                success=False,
                message="Sao lưu thất bại",
                error_code=type(exc).__name__,
            )
        self.logger.log(
            operator=self.operator,
            device=result.device,
            action=result.action,
            success=result.success,
            error_code=result.error_code,
        )
        return result
    
    def backup_many(
        self,
        devices: Iterable[NetworkDevice],
        group: Optional[str] = None,
    ) -> List[TaskResult]:
        """Sao lưu danh sách thiết bị đã kết nối, có thể lọc nhóm."""
        results = []

        for device in devices:
            if group is not None and device.info.group != group:
                continue

            result = self.backup(device)
            results.append(result)

        return results

    def read_snapshot(self, snapshot_id: str) -> ConfigSnapshot:
        """Đọc và kiểm tra một phiên bản backup."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", snapshot_id):
            raise ValueError("Mã phiên bản không hợp lệ")

        metadata_path = self.backup_dir / f"{snapshot_id}.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        if metadata["snapshot_id"] != snapshot_id:
            raise ValueError("Mã phiên bản không khớp")

        path = self.backup_dir / f"{snapshot_id}.txt"
        content = path.read_bytes().decode("utf-8")

        if sha256(content.encode("utf-8")).hexdigest() != metadata["sha256"]:
            raise ValueError("Nội dung backup không khớp SHA-256")

        snapshot = ConfigSnapshot(content=content, **metadata)
        captured_at = datetime.fromisoformat(snapshot.captured_at)

        if captured_at.utcoffset() is None:
            raise ValueError("Thời gian backup thiếu múi giờ")

        return snapshot

    def list_snapshots(self, device_name: str) -> List[ConfigSnapshot]:
        """Liệt kê các phiên bản hợp lệ, mới nhất trước."""
        snapshots = []

        for metadata_path in self.backup_dir.glob("*.json"):
            try:
                snapshot = self.read_snapshot(metadata_path.stem)

                if snapshot.device_name == device_name:
                    snapshots.append(snapshot)

            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                self.logger.log(
                    operator=self.operator,
                    device=device_name,
                    action="list_snapshots",
                    success=False,
                    error_code=type(exc).__name__,
                )

        return sorted(
            snapshots,
            key=lambda item: datetime.fromisoformat(item.captured_at),
            reverse=True,
        )

    def search_snapshots(
        self, device_name: str, keyword: str
    ) -> List[ConfigSnapshot]:
        """Tìm phiên bản theo mã hoặc thời gian backup."""
        keyword = keyword.strip().lower()

        return [
            snapshot
            for snapshot in self.list_snapshots(device_name)
            if keyword in snapshot.snapshot_id.lower()
            or keyword in snapshot.captured_at.lower()
        ]

    def backup_with_connection(self, device: NetworkDevice) -> TaskResult:
        """Kết nối, sao lưu rồi ngắt kết nối thiết bị."""
        try:
            device.connect()
        except Exception as exc:
            result = TaskResult(
                device=device.info.name,
                action="backup",
                success=False,
                message="Không thể kết nối thiết bị",
                error_code=type(exc).__name__,
            )
            self.logger.log(
                operator=self.operator,
                device=result.device,
                action=result.action,
                success=result.success,
                error_code=result.error_code,
            )
        else:
            result = self.backup(device)
        finally:
            try:
                device.disconnect()
            except Exception as exc:
                self.logger.log(
                    operator=self.operator,
                    device=device.info.name,
                    action="disconnect",
                    success=False,
                    error_code=type(exc).__name__,
                )

        return result