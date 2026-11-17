"""TV5 - verify device configuration after deploy or restore.

Verification here is intentionally conservative about conflicting identity
settings. A subset-of-lines result is NOT proof of a full device restore;
RestoreManager performs an additional exact read-back comparison.
"""

import hashlib
import logging
import re
from collections import Counter
from typing import Any, Dict, List

from core.base import NetworkDevice

logger = logging.getLogger(__name__)


class VerificationService:
    """Verify configuration content read from a NetworkDevice adapter."""

    @staticmethod
    def _lines(content: str) -> List[str]:
        if not isinstance(content, str):
            raise TypeError("Configuration must be a string")
        return [line.strip() for line in content.splitlines() if line.strip()]

    @staticmethod
    def compute_hash(content: str) -> str:
        """Compatible SHA-256 normalization: ignore blank lines/indentation."""
        normalized = "\n".join(VerificationService._lines(content))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _hostnames(content: str, platform: str) -> List[str]:
        """Extract hostname assignments relevant to the platform."""
        if platform == "frr":
            # FRR uses `hostname VALUE` as a top-level config command.
            return re.findall(r"(?m)^\s*hostname\s+(\S+)\s*$", content)
        if platform == "mikrotik":
            names = []
            for raw in content.splitlines():
                line = raw.strip()
                if re.match(r"^/system\s+identity\s+set\s+", line):
                    match = re.search(r'(?:^|\s)name=(?:"([^"]+)"|(\S+))', line)
                    if match:
                        names.append(match.group(1) or match.group(2))
            return names
        return []

    def verify_config_match(self, device: NetworkDevice, expected_config: str) -> Dict[str, Any]:
        """Verify expected lines while rejecting conflicting hostname values.

        This method is a presence check for *deploy*. Full restore must also
        verify exact canonical configuration (done by RestoreManager).
        """
        name = device.info.name
        try:
            running = device.get_running_config()
            expected_lines = [line for line in self._lines(expected_config)
                              if not line.startswith(("#", "!"))]
            running_lines = [line for line in self._lines(running)
                             if not line.startswith(("#", "!"))]

            expected_counts = Counter(expected_lines)
            actual_counts = Counter(running_lines)
            missing = list((expected_counts - actual_counts).elements())

            platform = device.info.platform.strip().lower()
            actual_hostnames = self._hostnames(running, platform)
            expected_hostnames = self._hostnames(expected_config, platform)
            unique_actual = set(actual_hostnames)
            conflicting_hostname = len(unique_actual) > 1
            wrong_hostname = bool(expected_hostnames) and (
                len(set(expected_hostnames)) != 1
                or unique_actual != set(expected_hostnames)
            )

            exact = self.compute_hash(expected_config) == self.compute_hash(running)
            passed = not missing and not conflicting_hostname and not wrong_hostname
            return {
                "device_name": name,
                "passed": passed,
                "exact_hash_match": exact,
                "missing_lines": missing,
                "conflicting_hostname": conflicting_hostname,
                "wrong_hostname": wrong_hostname,
                "actual_hostnames": actual_hostnames,
            }
        except Exception as exc:
            logger.error("[Verification] Error reading %s: %s", name, exc)
            return {"device_name": name, "passed": False, "error": str(exc)}
