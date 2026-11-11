import hashlib
import logging
from typing import Dict, Any, List
from core.base import NetworkDevice

logger = logging.getLogger(__name__)


class VerificationService:
    """Kiểm chứng cấu hình sau khi khôi phục hoặc triển khai (TV5)."""

    @staticmethod
    def compute_hash(content: str) -> str:
        """Tính SHA-256 hash sau khi chuẩn hóa khoảng trắng và dòng trống."""
        normalized = "\n".join(
            line.strip() for line in content.strip().splitlines() if line.strip()
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def verify_config_match(self, device: NetworkDevice, expected_config: str) -> Dict[str, Any]:
        device_name = device.info.name
        try:
            running_config = device.get_running_config()
            expected_hash = self.compute_hash(expected_config)
            running_hash = self.compute_hash(running_config)

            is_exact_match = expected_hash == running_hash
            expected_lines = [
                line.strip()
                for line in expected_config.splitlines()
                if line.strip() and not line.strip().startswith(("#", "!"))
            ]
            missing_lines = [
                line for line in expected_lines if line not in running_config
            ]
            passed = is_exact_match or (len(missing_lines) == 0)

            return {
                "device_name": device_name,
                "passed": passed,
                "exact_hash_match": is_exact_match,
                "missing_lines": missing_lines,
            }
        except Exception as e:
            logger.error(f"[Verification] Lỗi đọc running config từ {device_name}: {e}")
            return {
                "device_name": device_name,
                "passed": False,
                "error": str(e),
            }
