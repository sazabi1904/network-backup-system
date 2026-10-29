"""Audit logger: tranh ghi mat khau / lenh co thong tin nhay cam."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

SENSITIVE_TOKENS = ("password", "secret", "token", "community", "private-key", "plaintext-password", "authentication")


def safe_command(command: str) -> str:
    if any(token in command.lower() for token in SENSITIVE_TOKENS):
        return "[REDACTED SENSITIVE COMMAND]"
    return command


class AuditLogger:
    def __init__(self, path: Path = Path("logs/audit.jsonl")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, operator: str, device: str, action: str,
            success: bool, commands: Optional[Sequence[str]] = None,
            error_code: Optional[str] = None) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operator": operator,
            "device": device,
            "action": action,
            "commands": [safe_command(c) for c in (commands or [])],
            "status": "success" if success else "failure",
            "error_code": error_code,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
