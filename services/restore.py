import logging
from typing import Any
from core.base import NetworkDevice
from core.models import ConfigSnapshot, TaskResult
from services.verification import VerificationService
from services.exceptions import DeviceRestoreError

logger = logging.getLogger(__name__)


class RestoreManager:
    """Triển khai RestoreService (TV5): Quản lý khôi phục và Rollback cấu hình từ ConfigSnapshot."""

    def __init__(self, verifier: VerificationService = None):
        self.verifier = verifier or VerificationService()

    def validate_snapshot(self, device: NetworkDevice, snapshot: ConfigSnapshot) -> bool:
        """Kiểm tra tính hợp lệ của platform và nội dung snapshot trước khi restore."""
        dev_platform = device.info.platform.lower()
        snap_platform = snapshot.platform.lower()

        if dev_platform != snap_platform:
            logger.error(f"[Restore] Sai lệch nền tảng: Thiết bị '{dev_platform}' != Snapshot '{snap_platform}'")
            return False

        if not snapshot.content or not snapshot.content.strip():
            logger.error("[Restore] Nội dung snapshot khôi phục trống.")
            return False

        return True

    def restore(self, device: NetworkDevice, snapshot: ConfigSnapshot) -> TaskResult:
        """Thực hiện khôi phục cấu hình cho thiết bị từ ConfigSnapshot của TV4."""
        device_name = device.info.name
        snapshot_id = snapshot.snapshot_id
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
            if not restore_success:
                raise DeviceRestoreError("Phương thức restore_config() trả về False hoặc không xác minh được.")

            # 3. Kiểm chứng lại trạng thái cấu hình sau khôi phục
            verify_res = self.verifier.verify_config_match(device, snapshot.content)
            if not verify_res.get("passed"):
                raise DeviceRestoreError(f"Kiểm chứng cấu hình sau khôi phục thất bại: {verify_res}")

            logger.info(f"[Restore] Khôi phục thành công thiết bị '{device_name}'.")
            return TaskResult(
                device=device_name,
                action="restore",
                success=True,
                message="Khôi phục cấu hình thành công",
                data=verify_res
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
