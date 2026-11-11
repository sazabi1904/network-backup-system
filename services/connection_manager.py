from os import getenv

from services.logger import AuditLogger
from core.exceptions import (
    DeviceAuthenticationError,
    DeviceConnectionError,
    DeviceTimeoutError,
)
from dataclasses import asdict
from typing import Callable, Dict, Iterable, List, Optional

from core.base import NetworkDevice
from core.factory import DeviceFactory
from core.models import DeviceInfo, TaskResult

from concurrent.futures import ThreadPoolExecutor, as_completed

class ConnectionManager:
    """Quản lý kết nối đồng thời tới các thiết bị."""

    def __init__(self, max_workers: int = 4, demo: bool = False) -> None:
        if type(max_workers) is not int or max_workers <= 0:
            raise ValueError("max_workers phải là số nguyên dương")

        if type(demo) is not bool:
            raise TypeError("demo phải là True hoặc False")

        self.max_workers = max_workers
        self.demo = demo
        self._logger_error = None
        try:
            self.logger = AuditLogger()
        except OSError as exc:
            self.logger = None
            self._logger_error = type(exc).__name__
        self.operator = getenv("APP_OPERATOR", "tv3")
    
    def _log_result(
        self, result: TaskResult, action: str, success: bool,
        error_code: Optional[str],
    ) -> None:
        """Giữ kết quả thiết bị khi tạo hoặc ghi audit log thất bại."""
        if self.logger is None:
            result.data["logging_error"] = self._logger_error
            return
        try:
            self.logger.log(
                self.operator, result.device, action, success,
                error_code=error_code,
            )
        except OSError as exc:
            result.data["logging_error"] = type(exc).__name__

    @staticmethod
    def _connection_error_status(error: Exception) -> str:
        """Phân loại lỗi để đưa vào báo cáo kết nối."""
        if isinstance(error, DeviceAuthenticationError):
            return "authentication_failed"

        if isinstance(error, DeviceTimeoutError):
            return "timeout"

        if isinstance(error, DeviceConnectionError):
            return "offline"

        return "error"

    def _run_one(
        self,
        info: DeviceInfo,
        operation: Optional[Callable[[NetworkDevice], TaskResult]] = None,
    ) -> TaskResult:
        """Kết nối, thực hiện tác vụ rồi đóng phiên của một thiết bị."""
        device = None
        data = {
            "device_info": asdict(info),
            "connection_status": "error",
            "demo": self.demo,
        }
        action = "check_connection" if operation is None else "device_operation"
        result = TaskResult(
            device=info.name,
            action=action,
            success=False,
            message="Không thực hiện được tác vụ",
        )

        try:
            device = DeviceFactory.create(info, demo=self.demo)
            device.connect()
            data["connection_status"] = "online"

            if operation is None:
                result.success = True
                result.message = "Kết nối thành công"
            else:
                candidate = operation(device)
                if (
                    not isinstance(candidate, TaskResult)
                    or candidate.device != info.name
                    or not isinstance(candidate.data, dict)
                ):
                    raise TypeError("Tác vụ phải trả TaskResult hợp lệ")

                result = candidate

        except Exception as exc:
            result.success = False
            result.message = "Không thực hiện được tác vụ"
            result.error_code = type(exc).__name__

            if data["connection_status"] != "online":
                data["connection_status"] = self._connection_error_status(exc)

        finally:
            if device is not None:
                try:
                    device.disconnect()
                except Exception as exc:
                    data["disconnect_error"] = type(exc).__name__

        result.data = dict(result.data)
        result.data.update(data)
        return result

    def run(
        self,
        infos: Iterable[DeviceInfo],
        operation: Optional[Callable[[NetworkDevice], TaskResult]] = None,
    ) -> List[TaskResult]:
        """Chạy tác vụ đồng thời, trả kết quả theo thứ tự đầu vào."""
        device_infos = list(infos)

        if any(not isinstance(info, DeviceInfo) for info in device_infos):
            raise TypeError("Danh sách phải chứa các DeviceInfo")

        if len({info.name for info in device_infos}) != len(device_infos):
            raise ValueError("Danh sách có tên thiết bị trùng")

        if operation is not None and not callable(operation):
            raise TypeError("operation phải là một hàm")

        if not device_infos:
            return []

        completed: Dict[int, TaskResult] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._run_one, info, operation): index
                for index, info in enumerate(device_infos)
            }

            for future in as_completed(futures):
                completed[futures[future]] = future.result()

        results = [completed[index] for index in range(len(device_infos))]

        for result in results:
            self._log_result(
                result, result.action, result.success, result.error_code,
            )

            if "disconnect_error" in result.data:
                self._log_result(
                    result, "disconnect", False, result.data["disconnect_error"],
                )

        return results