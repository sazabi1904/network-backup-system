"""TV5 - verify device configuration after deploy or restore.

Deploy verifies its supported scope; restore compares the complete canonical
snapshot without discarding ordering, indentation or extra configuration.
"""

import hashlib
import logging
import re
import time
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
        """Require exact canonical state and reject conflicting hostname values."""
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

            normalize = getattr(device, 'normalize_config_for_verification', lambda value: value)
            expected_canonical = self._canonical(normalize(expected_config))
            actual_canonical = self._canonical(normalize(running))
            exact = expected_canonical == actual_canonical
            passed = exact and not conflicting_hostname and not wrong_hostname
            unexpected = list((actual_counts - expected_counts).elements())
            real_adapter = hasattr(device, 'write_scopes')
            return {
                "device_name": name,
                "passed": passed,
                "exact_hash_match": exact,
                "missing_lines": (['<configuration omitted>'] if missing else []) if real_adapter else missing,
                "unexpected_lines": (['<configuration omitted>'] if unexpected else []) if real_adapter else unexpected,
                "missing_line_count":len(missing),
                "unexpected_line_count":len(unexpected),
                "verification_mode": "exact-configuration",
                "conflicting_hostname": conflicting_hostname,
                "wrong_hostname": wrong_hostname,
                "actual_hostnames": actual_hostnames,
            }
        except Exception as exc:
            logger.error("[Verification] Error reading %s: %s", name, exc)
            return {"device_name": name, "passed": False, "error": str(exc)}

    @staticmethod
    def _canonical(content):
        # Keep indentation, ordering, duplicates and block context.
        return '\n'.join(line.rstrip() for line in content.splitlines() if line.strip())

    def verify_commands_present(self, device, commands):
        """Deploy checks scope; restore uses exact configuration comparison."""
        try:
            checker = getattr(device, 'verify_config_commands', None)
            if callable(checker):
                result = checker(commands)
                if not isinstance(result, dict) or type(result.get('passed')) is not bool:
                    raise ValueError('Invalid adapter verification result')
                return result
            expected = Counter(self._lines('\n'.join(commands)))
            actual = Counter(self._lines(device.get_running_config()))
            missing = list((expected - actual).elements())
            return {'device_name':device.info.name, 'passed':bool(commands) and not missing,
                    'missing_lines':missing, 'verification_mode':'literal-command-lines'}
        except Exception as exc:
            return {'device_name':device.info.name, 'passed':False, 'error':type(exc).__name__}

    def verify_ospf_convergence(self, device, expected_neighbors, expected_routes=(), timeout=90):
        """Broadcast DROthers may be 2-Way; require at least one FULL adjacency.

        Every expected peer must be FULL/2-Way, and requested routes must be
        selected OSPF routes. A config read-back alone never passes this check.
        """
        from devices.ospf_adapter import ipv4, prefix
        expected = {ipv4(rid) for rid in expected_neighbors}
        routes = {prefix(net) for net in expected_routes}
        if not expected or not 0 < timeout <= 600:
            raise ValueError('Expected peers and timeout in (0, 600] are required')
        deadline = time.monotonic() + timeout
        while True:
            neighbors = device.ospf_neighbors()
            states = {rid: [state.lower().replace('-', '') for state in neighbors.get(rid, [])]
                      for rid in expected}
            ready = all(any(state.startswith(('full', '2way')) for state in values)
                        for values in states.values())
            full = any(state.startswith('full') for values in states.values() for state in values)
            actual_routes = set(device.ospf_routes()) if routes else set()
            passed = ready and full and routes <= actual_routes
            result = {'device_name': device.info.name, 'passed': passed,
                      'verification_mode': 'ospf-convergence', 'neighbors': neighbors,
                      'expected_neighbors': sorted(expected), 'expected_routes': sorted(routes),
                      'missing_routes': sorted(routes - actual_routes)}
            if passed or time.monotonic() >= deadline:
                return result
            time.sleep(min(1, max(0, deadline - time.monotonic())))


class OSPFVerificationService(VerificationService):
    """Optional deploy policy: rollback when expected OSPF peers do not converge."""
    def __init__(self, expected_neighbors, timeout=90):
        self.expected_neighbors = expected_neighbors
        self.timeout = timeout

    def verify_commands_present(self, device, commands):
        configured = super().verify_commands_present(device, commands)
        if not configured.get('passed'):
            return configured
        return self.verify_ospf_convergence(device, self.expected_neighbors, timeout=self.timeout)
