import os
import logging
from typing import Dict, List, Sequence, Any, Optional
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from core.base import NetworkDevice
from core.models import TaskResult, ConfigSnapshot
from services.restore import RestoreManager
from services.verification import VerificationService
from services.exceptions import DeviceCommandError

logger = logging.getLogger(__name__)


class ConfigManager:
    """Triển khai ConfigService (TV5): Dry-run, Bulk Deploy cấu hình bằng Jinja2 tích hợp TV4 BackupManager."""

    def __init__(
        self,
        backup_manager: Any = None,  # TV4 BackupManager để tạo backup tự động
        restore_manager: RestoreManager = None,
        verifier: VerificationService = None,
        template_dir: Optional[str] = None,
    ):
        self.backup_manager = backup_manager
        self.restore_manager = restore_manager or RestoreManager()
        self.verifier = verifier or VerificationService()

        if not template_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            template_dir = os.path.join(base_dir, "templates")

        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _render_template(self, device: NetworkDevice, template_name: str, variables: Dict[str, Any]) -> str:
        platform = device.info.platform.lower()
        tpl_candidates = [
            f"{platform}_{template_name}",
            template_name if template_name.endswith(".j2") else f"{template_name}.j2",
            f"{platform}_ospf.j2"
        ]
        
        template = None
        for tpl in tpl_candidates:
            try:
                template = self.jinja_env.get_template(tpl)
                break
            except TemplateNotFound:
                continue

        if not template:
            raise FileNotFoundError(f"Không tìm thấy template Jinja2 phù hợp cho {platform} với tên '{template_name}'.")

        ctx = {
            **variables,
            "hostname": device.info.name,
            "router_id": variables.get("router_id", device.info.host)
        }
        return template.render(**ctx).strip()

    def dry_run(
        self,
        devices: Sequence[NetworkDevice],
        template_name: str,
        variables: Dict[str, Any],
    ) -> List[TaskResult]:
        """Thực hiện Dry-run: chỉ render cấu hình dự kiến, TUYỆT ĐỐI KHÔNG gọi push_config."""
        results: List[TaskResult] = []

        for device in devices:
            dev_name = device.info.name
            try:
                rendered_config = self._render_template(device, template_name, variables)
                results.append(
                    TaskResult(
                        device=dev_name,
                        action="dry_run",
                        success=True,
                        message=f"Dry-run thành công cho {dev_name}",
                        data={"rendered_config": rendered_config}
                    )
                )
            except Exception as e:
                results.append(
                    TaskResult(
                        device=dev_name,
                        action="dry_run",
                        success=False,
                        message=f"Lỗi render template: {str(e)}",
                        error_code="RENDER_ERROR"
                    )
                )

        logger.info(f"[ConfigManager] Hoàn tất Dry-run cho {len(devices)} thiết bị.")
        return results

    def deploy(
        self,
        devices: Sequence[NetworkDevice],
        template_name: str,
        variables: Dict[str, Any],
    ) -> List[TaskResult]:
        """Quy trình triển khai thật: Backup (TV4) -> Deploy -> Verify -> Tự động Rollback nếu lỗi."""
        results: List[TaskResult] = []

        for device in devices:
            dev_name = device.info.name
            snapshot_before: Optional[ConfigSnapshot] = None

            try:
                # 1. Render cấu hình từ Jinja2
                config_text = self._render_template(device, template_name, variables)
                
                # Chuyển đổi chuỗi lệnh thành List[str] theo đúng yêu cầu push_config của NetworkDevice
                commands_list = [line.strip() for line in config_text.splitlines() if line.strip() and not line.strip().startswith("#")]

                # 2. Tạo backup trước khi thay đổi thật bằng TV4 BackupManager
                if self.backup_manager and hasattr(self.backup_manager, "backup"):
                    # Lấy snapshot mới nhất vừa tạo hoặc danh sách snapshot để làm mốc rollback
                    self.backup_manager.backup(device)
                    snapshots = self.backup_manager.list_snapshots(dev_name)
                    if snapshots:
                        snapshot_before = snapshots[0] # Snapshot mới nhất
                    logger.info(f"[ConfigManager] Đã tạo bản backup dự phòng trước khi deploy cho {dev_name}.")

                # 3. Đẩy danh sách lệnh List[str] xuống thiết bị qua push_config()
                push_output = device.push_config(commands_list)
                
                results.append(
                    TaskResult(
                        device=dev_name,
                        action="deploy",
                        success=True,
                        message=f"Triển khai cấu hình thành công cho {dev_name}",
                        data={"push_output": push_output}
                    )
                )

            except Exception as e:
                err_msg = f"Lỗi triển khai cấu hình trên {dev_name}: {str(e)}"
                logger.error(f"[ConfigManager] {err_msg}")

                # 4. Tự động kích hoạt Rollback nếu có snapshot dự phòng từ TV4
                rolled_back = False
                if snapshot_before and self.restore_manager:
                    try:
                        rb_res = self.restore_manager.restore(device, snapshot_before)
                        rolled_back = rb_res.success
                        logger.info(f"[ConfigManager] Đã tự động rollback thiết bị {dev_name} thành công.")
                    except Exception as re:
                        logger.error(f"[ConfigManager] Rollback thất bại cho {dev_name}: {re}")

                results.append(
                    TaskResult(
                        device=dev_name,
                        action="deploy",
                        success=False,
                        message=err_msg,
                        data={"rolled_back": rolled_back},
                        error_code="DEPLOY_EXECUTION_ERROR"
                    )
                )

        logger.info(f"[ConfigManager] Hoàn tất Bulk Deploy cho {len(devices)} thiết bị.")
        return results
