
import os
import logging
from typing import Dict, List, Sequence, Any, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

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
        self.verifier = verifier or VerificationService()
        self.restore_manager = restore_manager or RestoreManager(verifier=self.verifier)

        if not template_dir:
            base_dir = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            template_dir = os.path.join(base_dir, "templates")

        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
            autoescape=False,  # Cấu hình CLI không phải HTML.
        )

    def _render_template(
        self,
        device: NetworkDevice,
        template_name: str,
        variables: Dict[str, Any],
    ) -> str:
        """Render template phù hợp với nền tảng thiết bị."""

        platform = device.info.platform.strip().lower()
        # Không tự đổi sang template OSPF nếu người dùng yêu cầu template khác.
        name = template_name[:-3] if template_name.endswith(".j2") else template_name
        if name in ('ospf', f'{platform}_ospf'):
            from devices.ospf_adapter import validate_variables
            validate_variables(variables)
        if not name or "/" in name or "\\" in name or ".." in name:
            raise ValueError("Tên template không hợp lệ")
        tpl_candidates = [f"{platform}_{name}.j2", f"{name}.j2"]

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

    @staticmethod
    def _commands(config_text: str) -> List[str]:
        """Chuyển template thành các dòng lệnh, bỏ comment và dòng rỗng."""
        commands = [
            line.strip() for line in config_text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "!"))
        ]
        if not commands:
            raise ValueError("Template không tạo ra lệnh cấu hình hợp lệ")
        return commands

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

                if not self._commands(rendered_config):
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

    def deploy(self, devices, template_name, variables):
        from core.operation_lock import device_operation
        results = []
        for device in devices:
            try:
                with device_operation(device):
                    results.extend(self._deploy([device], template_name, variables))
            except RuntimeError as exc:
                results.append(TaskResult(device.info.name, 'deploy', False, str(exc),
                                          error_code='DEVICE_BUSY'))
        return results

    def _deploy(
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
        - Có xác minh dòng lệnh sau deploy (FakeDevice).
        - Với MikroTik/FRR thật phải kiểm tra trạng thái theo nền tảng.
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

                commands_list = self._commands(config_text)

                if getattr(device, 'write_scopes', None) == ():
                    raise RuntimeError('Adapter is read-only; enable an explicit write scope')
                preflight = getattr(device, 'validate_config_commands', None)
                if callable(preflight):
                    preflight(commands_list)

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

                backup_result = self.backup_manager.backup(device)

                if not isinstance(backup_result, TaskResult) or not backup_result.success:
                    raise RuntimeError(
                        f"Backup thất bại trên {dev_name}: "
                        f"{getattr(backup_result, 'message', 'Kết quả backup không hợp lệ')}"
                    )
                # ID trả về bởi TV4 là định danh snapshot vừa được tạo.
                snapshot_id = backup_result.data.get("snapshot_id")
                if not isinstance(snapshot_id, str) or not snapshot_id:
                    raise RuntimeError("Backup không trả về snapshot_id hợp lệ")

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

                # Dựa vào ID TV4 trả về, tuyệt đối không lấy snapshots[0].
                matches = [snap for snap in snapshots if snap.snapshot_id == snapshot_id]
                if len(matches) != 1:
                    raise RuntimeError("Không tìm được đúng snapshot vừa backup")
                snapshot_before = matches[0]
                if not self.restore_manager.validate_snapshot(device, snapshot_before):
                    raise RuntimeError("Snapshot dự phòng không hợp lệ")
                expected_hash = backup_result.data.get("sha256")
                if expected_hash and expected_hash != snapshot_before.sha256:
                    raise RuntimeError("SHA-256 backup không khớp metadata snapshot")

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
                    "[ConfigManager] Đã gửi cấu hình tới %s; bắt đầu xác minh.",
                    dev_name,
                )
                verification = self.verifier.verify_commands_present(device, commands_list)
                if not verification.get("passed"):
                    raise RuntimeError(f"Xác minh sau deploy thất bại: {verification}")

                results.append(
                    TaskResult(
                        device=dev_name,
                        action="deploy",
                        success=True,
                        message=f"Đã gửi lệnh và xác minh cấu hình cho {dev_name}",
                        data={
                            "push_output": push_output,
                            "verified": True,
                            "verification": verification,
                            "snapshot_id": snapshot_before.snapshot_id,
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
                rollback_attempted = False

                # -----------------------------------------
                # BƯỚC 6: ROLLBACK KHI DEPLOY LỖI
                # -----------------------------------------
                # Chỉ rollback khi thao tác push
                # đã bắt đầu và có snapshot dự phòng.
                if push_started and snapshot_before is not None:
                    rollback_attempted = True

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
                            "rollback_attempted": rollback_attempted,
                            "rollback_error": rollback_error,
                            "push_started": push_started,
                            "adapter_error_code": getattr(e, 'code', None),
                            "may_have_applied": getattr(e, 'may_have_applied', push_started),
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
