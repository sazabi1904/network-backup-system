
"""TV4: Backup, list snapshots and compare configurations.

Caller connects/disconnects the device.
BackupManager only stores snapshots.
"""

import difflib
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

from core.base import NetworkDevice
from core.models import ConfigSnapshot, TaskResult


class BackupManager:
    """Save configuration files and verify their SHA-256 hashes."""

    def __init__(self, backup_dir: str = "backups") -> None:
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "device"

    @staticmethod
    def _parse_time(value: str) -> datetime:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def backup(self, device: NetworkDevice) -> TaskResult:
        """Save one snapshot from a connected device."""
        name = device.info.name

        try:
            config = device.get_running_config()

            if not isinstance(config, str) or not config.strip():
                raise ValueError("Empty or invalid configuration")

            
            # Gio Viet Nam: UTC+7
            vietnam_tz = timezone(timedelta(hours=7))
            now = datetime.now(vietnam_tz)

            # Thoi gian luu trong metadata JSON
            captured_at = now.isoformat()

            # Ten file co ngay gio va ma chong trung
            snapshot_id = (
                f"{self._safe_name(name)}_"
                f"{now.strftime('%Y%m%d_%H%M%S')}_"
                f"{uuid.uuid4().hex[:8]}"
)


            content_bytes = config.encode("utf-8")
            sha256 = hashlib.sha256(content_bytes).hexdigest()
            content_file = f"{snapshot_id}.cfg"

            snapshot = ConfigSnapshot(
                snapshot_id=snapshot_id,
                device_name=name,
                platform=device.info.platform,
                captured_at=captured_at,
                content=config,
                sha256=sha256,
            )

            meta = {
                "snapshot_id": snapshot.snapshot_id,
                "device_name": snapshot.device_name,
                "platform": snapshot.platform,
                "captured_at": snapshot.captured_at,
                "sha256": snapshot.sha256,
                "scope": snapshot.scope,
                "content_file": content_file,
            }

            cfg_path = self.backup_dir / content_file
            meta_path = self.backup_dir / f"{snapshot_id}.json"

            tmp_cfg = (
                self.backup_dir / f".{snapshot_id}.cfg.tmp"
            )
            tmp_meta = (
                self.backup_dir / f".{snapshot_id}.json.tmp"
            )

            if cfg_path.exists() or meta_path.exists():
                raise FileExistsError(
                    "Snapshot ID already exists"
                )

            try:
                # Ghi file tam truoc
                tmp_cfg.write_bytes(content_bytes)
                tmp_meta.write_text(
                    json.dumps(
                        meta,
                        ensure_ascii=False,
                        indent=2
                    ),
                    encoding="utf-8",
                )

                # Cong bo file hoan chinh
                tmp_cfg.replace(cfg_path)
                tmp_meta.replace(meta_path)

            except Exception:
                # Don dep neu ghi backup that bai
                for path in (
                    tmp_cfg, tmp_meta, cfg_path, meta_path
                ):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise

            return TaskResult(
                device=name,
                action="backup",
                success=True,
                message="Backup completed",
                data={
                    "snapshot_id": snapshot_id,
                    "sha256": sha256,
                },
            )

        except Exception as exc:
            return TaskResult(
                device=name,
                action="backup",
                success=False,
                message="Backup failed",
                error_code=type(exc).__name__,
            )

    def list_snapshots(
        self, device_name: str
    ) -> List[ConfigSnapshot]:
        """Read and validate snapshots of one device."""

        snapshots = []
        prefix = self._safe_name(device_name)

        # Chi tim metadata theo tien to cua thiet bi
        for meta_path in self.backup_dir.glob(
            f"{prefix}_*.json"
        ):
            meta = json.loads(
                meta_path.read_text(encoding="utf-8")
            )

            if meta["device_name"] != device_name:
                continue

            snapshot_id = meta["snapshot_id"]
            content_file = Path(
                meta["content_file"]
            ).name

            if (
                meta_path.stem != snapshot_id
                or content_file != f"{snapshot_id}.cfg"
            ):
                raise ValueError(
                    "Invalid snapshot metadata"
                )

            content_bytes = (
                self.backup_dir / content_file
            ).read_bytes()

            digest = hashlib.sha256(
                content_bytes
            ).hexdigest()

            if digest != meta["sha256"]:
                raise ValueError(
                    f"Corrupted snapshot: {snapshot_id}"
                )

            snapshots.append(
                ConfigSnapshot(
                    snapshot_id=snapshot_id,
                    device_name=meta["device_name"],
                    platform=meta["platform"],
                    captured_at=meta["captured_at"],
                    content=content_bytes.decode("utf-8"),
                    sha256=meta["sha256"],
                    scope=meta.get(
                        "scope",
                        "device-supported-config"
                    ),
                )
            )

        # Sap xep theo thoi diem thuc te, khong theo chuoi
        return sorted(
            snapshots,
            key=lambda s: self._parse_time(s.captured_at),
            reverse=True,
        )

    def diff(
        self,
        left: ConfigSnapshot,
        right: ConfigSnapshot
    ) -> str:
        """Compare two snapshots of the same device."""

        if left.device_name != right.device_name:
            raise ValueError(
                "Cannot compare snapshots from different devices"
            )

        return "".join(
            difflib.unified_diff(
                left.content.splitlines(keepends=True),
                right.content.splitlines(keepends=True),
                fromfile=left.snapshot_id,
                tofile=right.snapshot_id,
            )
        )
