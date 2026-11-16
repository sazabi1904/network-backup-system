
import os
import logging
from typing import Dict, List, Sequence, Any, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from core.base import NetworkDevice
from core.models import TaskResult, ConfigSnapshot
from services.restore import RestoreManager
from services.verification import VerificationService

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Quản lý cấu hình thiết bị mạng (TV5).

    Chức năng:
    - Render cấu hình bằng Jinja2.
    - Dry-run xem trước cấu hình.
    - Backup trước khi deploy.
    - Deploy cấu hình hàng loạt.
    - Thử rollback khi deploy phát sinh lỗi.
    """

    def __init__(
        self,
        backup_manager: Any = None,
        restore_manager: Optional[RestoreManager] = None,
        verifier: Optional[VerificationService] = None,
        template_dir: Optional[str] = None,
    ):
        self.backup_manager = backup_manager
        self.restore_manager = restore_manager or RestoreManager()
        self.verifier = verifier or VerificationService()

        if not template_dir:
            base_dir = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            template_dir = os.path.join(base_dir, "templates")

        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _render_template(
        self,
        device: NetworkDevice,
        template_name: str,
        variables: Dict[str, Any],
    ) -> str:
        """Render template phù hợp với nền tảng thiết bị."""

        platform = device.info.platform.lower()

        tpl_candidates = [
            f"{platform}_{template_name}",
            (
                template_name
                if template_name.endswith(".j2")
                else f"{template_name}.j2"
            ),
            f"{platform}_ospf.j2",
        ]

        template = None

        for tpl in tpl_candidates:
            try:
                template = self.jinja_env.get_template(tpl)
                break
            except TemplateNotFound:
                continue

        if template is None:
            raise FileNotFoundError(
                f"Không tìm thấy template Jinja2 phù hợp "
                f"cho {platform} với tên '{template_name}'."
            )

        ctx = {
            **variables,
            "hostname": device.info.name,
            "router_id": variables.get(
                "router_id",
                device.info.host,
            ),
        }

        return template.render(**ctx).strip()

    def dry_run(
        self,
        devices: Sequence[NetworkDevice],
        template_name: str,
        variables: Dict[str, Any],
    ) -> List[TaskResult]:
        """
        Dry-run chỉ render cấu hình dự kiến.
        Không gọi push_config hoặc thay đổi router.
        """

        results: List[TaskResult] = []

        for device in devices:
            dev_name = device.info.name

            try:
                rendered_config = self._render_template(
                    device,
                    template_name,
                    variables,
                )

                if not rendered_config.strip():
                    raise ValueError(
                        "Template tạo ra cấu hình rỗng."
                    )

                results.append(
                    TaskResult(
                        device=dev_name,
                        action="dry_run",
                        success=True,
                        message=(
                            f"Dry-run thành công cho {dev_name}"
                        ),
                        data={
                            "rendered_config": rendered_config
                        },
                    )
                )

            except Exception as e:
                logger.error(
                    "[ConfigManager] Dry-run lỗi trên %s: %s",
                    dev_name,
                    e,
                )

                results.append(
                    TaskResult(
                        device=dev_name,
                        action="dry_run",
                        success=False,
                        message=(
                            f"Lỗi render template: {str(e)}"
                        ),
                        error_code="RENDER_ERROR",
                    )
                )

        logger.info(
            "[ConfigManager] Hoàn tất Dry-run cho %d thiết bị.",
            len(devices),
        )

        return results

    def deploy(
        self,
        devices: Sequence[NetworkDevice],
        template_name: str,
        variables: Dict[str, Any],
    ) -> List[TaskResult]:
        """
        Triển khai cấu hình.

        Quy trình:
        1. Render template.
        2. Backup cấu hình hiện tại.
        3. Kiểm tra backup thành công.
        4. Lấy snapshot dự phòng.
        5. Đẩy cấu hình xuống thiết bị.
        6. Nếu quá trình đẩy lỗi, thử rollback.

        Lưu ý:
        - Chưa tích hợp xác minh cấu hình sau deploy.
        - Cần xác nhận snapshot được chọn là bản vừa backup.
        """

        results: List[TaskResult] = []

        for device in devices:
            dev_name = device.info.name

            snapshot_before: Optional[ConfigSnapshot] = None

            # Đánh dấu đã bắt đầu thao tác thay đổi cấu hình.
            push_started = False

            # Kết quả rollback, mặc định chưa thực hiện.
            rolled_back = False

            try:
                # -----------------------------------------
                # BƯỚC 1: RENDER TEMPLATE
                # -----------------------------------------
                config_text = self._render_template(
                    device,
                    template_name,
                    variables,
                )

                commands_list = [
                    line.strip()
                    for line in config_text.splitlines()
                    if line.strip()
                    and not line.strip().startswith("#")
                ]

                if not commands_list:
                    raise ValueError(
                        f"Cấu hình tạo ra cho {dev_name} "
                        f"không có lệnh hợp lệ."
                    )

                logger.info(
                    "[ConfigManager] Đã render %d lệnh cho %s.",
                    len(commands_list),
                    dev_name,
                )

                # -----------------------------------------
                # BƯỚC 2: KIỂM TRA BACKUP MANAGER
                # -----------------------------------------
                if self.backup_manager is None:
                    raise RuntimeError(
                        "Chưa cấu hình BackupManager. "
                        "Không thể deploy an toàn."
                    )

                if not hasattr(
                    self.backup_manager,
                    "backup",
                ):
                    raise RuntimeError(
                        "BackupManager không có hàm backup()."
                    )

                if not hasattr(
                    self.backup_manager,
                    "list_snapshots",
                ):
                    raise RuntimeError(
                        "BackupManager không có hàm "
                        "list_snapshots()."
                    )

                # -----------------------------------------
                # BƯỚC 3: TẠO BACKUP
                # -----------------------------------------
                logger.info(
                    "[ConfigManager] Bắt đầu backup %s.",
                    dev_name,
                )

                backup_result = self.backup_manager.backup(
                    device
                )

                if not backup_result.success:
                    raise RuntimeError(
                        f"Backup thất bại trên {dev_name}: "
                        f"{backup_result.message}"
                    )

                logger.info(
                    "[ConfigManager] Backup thành công cho %s.",
                    dev_name,
                )

                # -----------------------------------------
                # BƯỚC 4: LẤY SNAPSHOT DỰ PHÒNG
                # -----------------------------------------
                snapshots = (
                    self.backup_manager.list_snapshots(
                        dev_name
                    )
                )

                if not snapshots:
                    raise RuntimeError(
                        f"Không tìm thấy snapshot "
                        f"của thiết bị {dev_name}."
                    )

                # Tạm dùng snapshot đầu tiên như code cũ.
                # Cần xác nhận với TV4 rằng danh sách
                # được sắp xếp mới nhất trước.
                snapshot_before = snapshots[0]

                logger.info(
                    "[ConfigManager] Đã chọn snapshot "
                    "dự phòng cho %s.",
                    dev_name,
                )

                # -----------------------------------------
                # BƯỚC 5: DEPLOY CẤU HÌNH
                # -----------------------------------------
                logger.info(
                    "[ConfigManager] Bắt đầu deploy %s.",
                    dev_name,
                )

                push_started = True

                push_output = device.push_config(
                    commands_list
                )

                logger.info(
                    "[ConfigManager] Đã gửi cấu hình tới %s.",
                    dev_name,
                )

                results.append(
                    TaskResult(
                        device=dev_name,
                        action="deploy",
                        success=True,
                        message=(
                            f"Đã gửi cấu hình thành công "
                            f"cho {dev_name}. "
                            "Chưa xác minh trạng thái "
                            "cấu hình thực tế."
                        ),
                        data={
                            "push_output": push_output,
                            "verified": False,
                        },
                    )
                )

            except Exception as e:
                err_msg = (
                    f"Lỗi triển khai cấu hình "
                    f"trên {dev_name}: {str(e)}"
                )

                logger.error(
                    "[ConfigManager] %s",
                    err_msg,
                )

                rollback_error = None

                # -----------------------------------------
                # BƯỚC 6: ROLLBACK KHI DEPLOY LỖI
                # -----------------------------------------
                # Chỉ rollback khi thao tác push
                # đã bắt đầu và có snapshot dự phòng.
                if push_started and snapshot_before is not None:

                    if self.restore_manager is not None:
                        try:
                            logger.warning(
                                "[ConfigManager] Bắt đầu "
                                "rollback %s.",
                                dev_name,
                            )

                            rb_res = (
                                self.restore_manager.restore(
                                    device,
                                    snapshot_before,
                                )
                            )

                            rolled_back = rb_res.success

                            if rolled_back:
                                logger.info(
                                    "[ConfigManager] "
                                    "Rollback %s thành công.",
                                    dev_name,
                                )
                            else:
                                rollback_error = (
                                    rb_res.message
                                )

                                logger.error(
                                    "[ConfigManager] "
                                    "Rollback %s thất bại: %s",
                                    dev_name,
                                    rollback_error,
                                )

                        except Exception as re:
                            rolled_back = False
                            rollback_error = str(re)

                            logger.error(
                                "[ConfigManager] "
                                "Rollback thất bại "
                                "cho %s: %s",
                                dev_name,
                                re,
                            )

                # -----------------------------------------
                # GHI KẾT QUẢ THẤT BẠI
                # -----------------------------------------
                results.append(
                    TaskResult(
                        device=dev_name,
                        action="deploy",
                        success=False,
                        message=err_msg,
                        data={
                            "rolled_back": rolled_back,
                            "rollback_error": rollback_error,
                            "push_started": push_started,
                        },
                        error_code="DEPLOY_EXECUTION_ERROR",
                    )
                )

        logger.info(
            "[ConfigManager] Hoàn tất Bulk Deploy "
            "cho %d thiết bị.",
            len(devices),
        )

        return results
