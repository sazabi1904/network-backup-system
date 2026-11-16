import logging
import hashlib
from typing import Optional

from core.base import NetworkDevice
from core.models import ConfigSnapshot, TaskResult
from services.verification import VerificationService
from core.exceptions import DeviceRestoreError

logger = logging.getLogger(__name__)


class RestoreManager:
    """Triển khai RestoreService (TV5): Quản lý khôi phục và Rollback cấu hình từ ConfigSnapshot."""

    def __init__(self, verifier: Optional[VerificationService] = None):
        self.verifier = verifier or VerificationService()

    def validate_snapshot(self, device: NetworkDevice, snapshot: ConfigSnapshot) -> bool:
        """Kiểm tra đúng thiết bị, nền tảng, phạm vi và hash của bản backup."""
        if not isinstance(snapshot, ConfigSnapshot):
            logger.error("[Restore] Snapshot không đúng kiểu ConfigSnapshot")
            return False
        if snapshot.device_name != device.info.name:
            logger.error("[Restore] Snapshot thuộc thiết bị khác")
            return False
        if not isinstance(snapshot.platform, str) or (
            snapshot.platform.strip().lower() != device.info.platform.strip().lower()
        ):
            logger.error("[Restore] Nền tảng snapshot không khớp")
            return False
        if not isinstance(snapshot.content, str) or not snapshot.content.strip():
            logger.error("[Restore] Snapshot rỗng hoặc không hợp lệ")
            return False
        if not isinstance(snapshot.sha256, str) or (
            hashlib.sha256(snapshot.content.encode("utf-8")).hexdigest()
            != snapshot.sha256.lower()
        ):
            logger.error("[Restore] Nội dung snapshot không khớp SHA-256")
            return False
        if snapshot.scope != "device-supported-config":
            logger.error("[Restore] Phạm vi snapshot chưa được hỗ trợ: %s", snapshot.scope)
            return False
        if not snapshot.snapshot_id or not snapshot.captured_at:
            logger.error("[Restore] Snapshot thiếu ID hoặc thời điểm")
            return False
        return True

    def restore(self, device: NetworkDevice, snapshot: ConfigSnapshot) -> TaskResult:
        """Thực hiện khôi phục cấu hình cho thiết bị từ ConfigSnapshot của TV4."""
        device_name = device.info.name
        snapshot_id = getattr(snapshot, "snapshot_id", "<invalid>")
        logger.info(f"[Restore] Bắt đầu khôi phục thiết bị '{device_name}' từ snapshot ID: {snapshot_id}")

        # 1. Validate snapshot
        if not self.validate_snapshot(device, snapshot):
            msg = "Snapshot không hợp lệ hoặc sai lệch nền tảng thiết bị."
            return TaskResult(
                device=device_name,
                action="restore",
                success=False,
                message=msg,
                error_code="INVALID_SNAPSHOT"
            )

        try:
            # 2. Gọi phương thức restore_config() của NetworkDevice (do TV2 adapter cung cấp)
            restore_success = device.restore_config(snapshot.content)
            if restore_success is not True:
                raise RuntimeError("restore_config() chưa xác nhận khôi phục thành công")

            # 3. Kiểm chứng lại trạng thái cấu hình sau khôi phục
            verify_res = self.verifier.verify_config_match(device, snapshot.content)
            if not verify_res.get("passed"):
                return TaskResult(
                    device=device_name, action="restore", success=False,
                    message="Đã thực hiện restore nhưng xác minh thất bại",
                    data=verify_res, error_code="RESTORE_VERIFY_FAILED",
                )

            logger.info(f"[Restore] Khôi phục thành công thiết bị '{device_name}'.")
            return TaskResult(
                device=device_name,
                action="restore",
                success=True,
                message="Khôi phục cấu hình thành công",
                data={"snapshot_id": snapshot_id, **verify_res}
            )

        except Exception as e:
            err_msg = f"Lỗi trong quá trình khôi phục thiết bị '{device_name}': {str(e)}"
            logger.error(f"[Restore] {err_msg}")
            return TaskResult(
                device=device_name,
                action="restore",
                success=False,
                message=err_msg,
                error_code="RESTORE_EXECUTION_ERROR"
            )
