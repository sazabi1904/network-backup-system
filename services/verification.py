import hashlib
import logging
from collections import Counter
from typing import Dict, Any, List
from core.base import NetworkDevice

logger = logging.getLogger(__name__)


class VerificationService:
    """Kiểm chứng cấu hình sau khi khôi phục hoặc triển khai (TV5)."""

    @staticmethod
    def _lines(content: str) -> List[str]:
        if not isinstance(content, str):
            raise TypeError("Cấu hình phải là chuỗi")
        return [line.strip() for line in content.splitlines() if line.strip()]

    @staticmethod
    def compute_hash(content: str) -> str:
        """Tính SHA-256 hash sau khi chuẩn hóa khoảng trắng và dòng trống."""
        normalized = "\n".join(VerificationService._lines(content))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def verify_config_match(self, device: NetworkDevice, expected_config: str) -> Dict[str, Any]:
        device_name = device.info.name
        try:
            running_config = device.get_running_config()
            expected_hash = self.compute_hash(expected_config)
            running_hash = self.compute_hash(running_config)

            is_exact_match = expected_hash == running_hash
            expected_lines = Counter(self._lines(expected_config))
            actual_lines = Counter(self._lines(running_config))
            # Restore yêu cầu khớp toàn bộ (bao gồm số lần xuất hiện từng dòng).
            # Không thể chỉ kiểm tra rằng lệnh mong đợi là chuỗi con của output.
            return {
                "device_name": device_name,
                "passed": is_exact_match,
                "exact_hash_match": is_exact_match,
                "missing_lines": list((expected_lines - actual_lines).elements()),
                "unexpected_lines": list((actual_lines - expected_lines).elements()),
            }
        except Exception as e:
            logger.error(f"[Verification] Lỗi đọc running config từ {device_name}: {e}")
            return {
                "device_name": device_name,
                "passed": False,
                "error": str(e),
            }

    def verify_commands_present(self, device: NetworkDevice, commands: List[str]) -> Dict[str, Any]:
        """Kiểm tra cơ bản cho FakeDevice; chưa thay thế xác minh theo nền tảng."""
        device_name = device.info.name
        try:
            if not commands:
                raise ValueError("Không có lệnh cần xác minh")
            running_config = device.get_running_config()
            expected = Counter(self._lines("\n".join(commands)))
            actual = Counter(self._lines(running_config))
            missing = list((expected - actual).elements())
            return {"device_name": device_name, "passed": not missing,
                    "missing_lines": missing, "verification_mode": "literal-command-lines"}
        except Exception as exc:
            logger.error("[Verification] Xác minh deploy %s lỗi: %s", device_name, exc)
            return {"device_name": device_name, "passed": False,
                    "error": str(exc), "verification_mode": "literal-command-lines"}
