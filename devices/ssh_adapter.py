"""Read-only NetworkDevice adapter shared by TV2/TV3/TV4/TV5."""
import re
import logging
import math
import time
from functools import partial
from typing import List, Optional

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout
from paramiko import SSHException

from core.base import NetworkDevice
from core.commands import COLLECTION_COMMANDS
from core.models import DeviceInfo
from core.settings import credentials_from_env
from core.exceptions import (DeviceAuthenticationError, DeviceConnectionError,
                             DeviceTimeoutError, DeviceCommandError,
                             UnsupportedFeatureError)

logger = logging.getLogger(__name__)


class SSHAdapter(NetworkDevice):
    write_scopes = ()
    DRIVERS = {"mikrotik": "mikrotik_routeros", "frr": "linux"}

    def __init__(self, info: DeviceInfo, host: Optional[str] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 timeout: float = 30, known_hosts: Optional[str] = None,
                 frr_shell: str = "auto", export_read_timeout: Optional[float] = None,
                 export_retries: int = 1):
        if not isinstance(info, DeviceInfo):
            raise TypeError("info must be DeviceInfo")
        if info.platform not in self.DRIVERS or not info.host or not info.name:
            raise ValueError("Expected mikrotik/frr and nonempty device name/host")
        if host is not None and host != info.host:
            raise ValueError("host must match info.host")
        if not 1 <= info.port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid port or timeout")
        export_read_timeout = timeout if export_read_timeout is None else export_read_timeout
        if not math.isfinite(export_read_timeout) or export_read_timeout <= 0:
            raise ValueError('export_read_timeout must be positive and finite')
        if type(export_retries) is not int or export_retries not in (0, 1):
            raise ValueError('export_retries must be 0 or 1')
        if (username is None) != (password is None):
            raise ValueError("Provide both username/password or use credential_ref")
        if frr_shell not in {"auto", "linux", "vtysh"}:
            raise ValueError("frr_shell must be auto, linux or vtysh")
        super().__init__(info)
        self.timeout, self.known_hosts = timeout, known_hosts
        self.frr_shell = frr_shell
        self._username, self._password = username, password
        self._connection = None
        self.export_read_timeout = export_read_timeout
        self.export_retries = export_retries
        self.export_diagnostics = []

    def _routeros_export(self):
        """Retry only the allowlisted read, never a deploy/restore operation.

        Keep the terminating prompt until validation, so neither a timeout nor
        RouterOS' own partial-export error can become a successful snapshot.
        """
        if self._connection is None:
            raise DeviceConnectionError('Device is not connected')
        self.export_diagnostics = []
        for attempt in range(1, self.export_retries + 2):
            started = time.monotonic()
            phase, reason, received = 'prompt_refresh', 'PROMPT_INVALID', None
            retryable = False
            error_type = DeviceCommandError
            try:
                if attempt > 1:
                    phase = 'reconnect'
                    self.connect()  # Same strict host keys and runtime credentials.
                phase = 'prompt_refresh'
                base = self._connection.set_base_prompt(
                    pattern=r'(?m:^[ \t]*\[[^\]\r\n]+@[^\]\r\n]+\][ \t]*>[ \t]*$)')
                if not isinstance(base, str) or not re.fullmatch(r'\[[^\]\r\n]+@[^\]\r\n]+\]', base):
                    raise DeviceCommandError('Invalid RouterOS root prompt')
                pattern = r'(?m:^[ \t]*' + re.escape(base) + r'[ \t]*>[ \t\r\n]*\Z)'
                phase, reason = 'export_read', 'EXPORT_INVALID'
                raw = self._connection.send_command(
                    '/export terse', expect_string=pattern, auto_find_prompt=False,
                    read_timeout=self.export_read_timeout, cmd_verify=True,
                    strip_prompt=False, strip_command=True)
                phase = 'export_validation'
                if not isinstance(raw, str):
                    raise DeviceCommandError('Invalid RouterOS export response')
                received = len(raw.encode('utf-8'))
                raw = raw.replace('\r\n', '\n').replace('\r', '\n')
                if re.search(r'(?mi)^\s*#\s*error\s+exporting\b', raw):
                    reason = 'EXPORT_INCOMPLETE'
                    raise DeviceCommandError('RouterOS reported an incomplete export')
                end = re.search(pattern, raw)
                if end is None:
                    reason = 'EXPORT_INCOMPLETE'
                    raise DeviceCommandError('Missing RouterOS export terminator')
                content = raw[:end.start()]
                if (not re.search(r'(?mi)^#.*RouterOS', content)
                        or not re.search(r'(?m)^/[a-z]', content)
                        or self._has_error(content)):
                    raise DeviceCommandError('Invalid RouterOS export content')
                self.export_diagnostics.append(dict(
                    attempt=attempt, phase='complete', code='OK', received_bytes=received,
                    elapsed_ms=round((time.monotonic()-started)*1000),
                    timeout_s=self.export_read_timeout))
                return content
            except (ReadTimeout, NetmikoTimeoutException, TimeoutError) as exc:
                if phase == 'export_read':
                    # Inspect locally for classification only; never log raw exceptions.
                    detail = str(exc).lower()
                    phase = ('command_echo' if 'command echo' in detail else
                             'output_prompt' if 'pattern not detected' in detail else 'export_read')
                reason, error_type = 'EXPORT_TIMEOUT', DeviceTimeoutError
                retryable = phase != 'reconnect'
            except (OSError, EOFError, SSHException):
                reason, error_type = 'EXPORT_CONNECTION_LOST', DeviceConnectionError
                retryable = phase != 'reconnect'
            except DeviceAuthenticationError:
                reason, error_type = 'EXPORT_AUTH_FAILED', DeviceAuthenticationError
            except DeviceTimeoutError:
                reason, error_type = 'EXPORT_TIMEOUT', DeviceTimeoutError
            except DeviceConnectionError:
                reason, error_type = 'EXPORT_CONNECTION_LOST', DeviceConnectionError
            except Exception:
                # Validation/rejected output is not retried as if it were transport loss.
                pass
            self._close_on_error()
            diagnostic = dict(attempt=attempt, phase=phase, code=reason,
                              elapsed_ms=round((time.monotonic()-started)*1000),
                              timeout_s=self.export_read_timeout, received_bytes=received)
            self.export_diagnostics.append(diagnostic)
            logger.warning('RouterOS export failed: phase=%s code=%s attempt=%d elapsed_ms=%d timeout_s=%s',
                           phase, reason, attempt, diagnostic['elapsed_ms'], self.export_read_timeout)
            if retryable and attempt <= self.export_retries:
                continue
            error = error_type(f'{reason}; phase={phase}; attempt={attempt}')
            error.code = reason
            error.diagnostics = tuple(dict(item) for item in self.export_diagnostics)
            raise error from None

    def _close_on_error(self):
        try:
            self.disconnect()
        except DeviceConnectionError:
            pass

    def connect(self) -> None:
        if self._connection is not None:
            return
        username, password = self._username, self._password
        if username is None:
            try:
                credentials = credentials_from_env(self.info.credential_ref)
                username, password = credentials.username, credentials.password
            except ValueError:
                raise DeviceAuthenticationError("Missing runtime credentials") from None
        params = dict(host=self.info.host, port=self.info.port,
                      device_type=self.DRIVERS[self.info.platform], username=username,
                      password=password, conn_timeout=self.timeout,
                      auth_timeout=self.timeout, banner_timeout=self.timeout,
                      ssh_strict=True, system_host_keys=True,
                      allow_agent=False, use_keys=False)
        if self.known_hosts:
            params.update(alt_host_keys=True, alt_key_file=self.known_hosts)
        try:
            # Let Netmiko open and prepare the SSH session.
            self._connection = ConnectHandler(**params)
        except NetmikoAuthenticationException:
            self._close_on_error()
            raise DeviceAuthenticationError("SSH authentication failed") from None
        except (NetmikoTimeoutException, ReadTimeout):
            self._close_on_error()
            raise DeviceTimeoutError("SSH connection timed out") from None
        except Exception:
            self._close_on_error()
            raise DeviceConnectionError("SSH failed; check host key, network and service") from None

    def disconnect(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                raise DeviceConnectionError("SSH disconnect failed") from None

    def _read(self, command: str, allow_empty: bool = False) -> str:
        if self._connection is None:
            raise DeviceConnectionError("Device is not connected")
        try:
            output = self._connection.send_command(
                command, read_timeout=self.timeout, strip_prompt=True, strip_command=True)
        except (ReadTimeout, NetmikoTimeoutException):
            self._close_on_error()
            raise DeviceTimeoutError("Device read timed out") from None
        except Exception:
            self._close_on_error()
            raise DeviceCommandError("Cannot read device output") from None
        if not isinstance(output, str) or (not allow_empty and not output.strip()):
            self._close_on_error()
            raise DeviceCommandError("Device returned empty output")
        return output.replace("\r\n", "\n").replace("\r", "\n")

    def _frr(self, command: str) -> str:
        if self.frr_shell == "vtysh":
            return self._read(command)
        output = self._read('vtysh -c "' + command + '"')
        # vtysh's own error, not bash's command-not-found, identifies a CLI login.
        if self.frr_shell == "auto" and re.search(r"(?mi)^%\s*Unknown command:\s*vtysh\b", output):
            return self._read(command)
        return output

    @staticmethod
    def _has_error(output: str) -> bool:
        return bool(re.search(
            r"(?mi)^\s*(?:%\s*(?:Unknown|Error|Can't)|(?:failure|error|syntax error|bad command name)\b|.*(?:command not found|permission denied|vtysh: not found))", output))

    def send_command(self, command: str) -> str:
        profile = COLLECTION_COMMANDS[self.info.platform]
        collection_commands = {value for value in profile.values() if value is not None}
        config_command = "/export terse" if self.info.platform == "mikrotik" else "show running-config"
        allowed = collection_commands | {config_command}
        if command not in allowed:
            raise DeviceCommandError("Read-only adapter: command is not supported")
        if self.info.platform == "mikrotik":
            if command == config_command:
                return self._routeros_export()
            # An empty RouterOS table is a valid collection result.
            output = self._read(command, allow_empty=command.endswith("terse without-paging"))
        else:
            output = self._frr(command)
        if command in collection_commands and re.search(
            r"(?mi)^\s*(?:%\s*Unknown command|bad command name)\b", output
        ):
            raise UnsupportedFeatureError("Device does not support this collection command")
        if self._has_error(output):
            # Collector records command errors per section and reads the next one.
            if command == config_command:
                self._close_on_error()
            raise DeviceCommandError("Device rejected the read-only command")
        return output

    def get_running_config(self) -> str:
        command = "/export terse" if self.info.platform == "mikrotik" else "show running-config"
        output = self.send_command(command)
        if self.info.platform == "mikrotik":
            # Only a complete CLI prompt line, never arbitrary bracketed config.
            output = "".join(line for line in output.splitlines(keepends=True)
                             if not re.fullmatch(r"\s*\[[^\]\r\n]+@[^\]\r\n]+\]\s*>\s*", line))
        if self.info.platform == "frr":
            valid = bool(re.search(r"(?m)^frr version \S+", output) and
                         re.search(r"(?m)^end\s*$", output) and output.rstrip().endswith("end"))
        else:
            valid = bool(re.search(r"(?mi)^#.*RouterOS", output) and
                         re.search(r"(?m)^/[a-z]", output))
        if not valid:
            self._close_on_error()
            raise DeviceCommandError("Invalid or incomplete running configuration")
        return output

    def probe(self) -> str:
        output = self.send_command("/system resource print" if self.info.platform == "mikrotik" else "show version")
        marker = "version:" if self.info.platform == "mikrotik" else "FRRouting"
        if marker not in output:
            self._close_on_error()
            raise DeviceCommandError("Unexpected device version output")
        return output

    def push_config(self, commands: List[str]) -> str:
        raise NotImplementedError("Read-only SSH adapter")

    def restore_config(self, backup: str) -> bool:
        raise NotImplementedError("Read-only SSH adapter")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


def register_device_adapters(*, timeout: float = 30,
                             known_hosts: Optional[str] = None,
                             frr_shell: str = "auto", write: bool = False,
                             write_scope: str = 'managed',
                             export_read_timeout: Optional[float] = None,
                             export_retries: int = 1) -> None:
    """Register builders; credentials are resolved at connect(), per TV1 contract."""
    from core.factory import DeviceFactory
    if write:
        from devices.write_adapter import WriteSSHAdapter
        if write_scope not in ('managed', 'ospf'):
            raise ValueError('Unknown write scope')
        adapter = WriteSSHAdapter
        if write_scope == 'ospf':
            from devices.ospf_adapter import OSPFSSHAdapter
            adapter = OSPFSSHAdapter
        for platform in ('mikrotik', 'frr'):
            DeviceFactory.register(platform, partial(adapter, timeout=timeout,
                known_hosts=known_hosts, frr_shell=frr_shell,
                export_read_timeout=export_read_timeout, export_retries=export_retries))
        return
    from devices.mikrotik import MikroTikDevice
    from devices.frr import FRRDevice
    DeviceFactory.register("mikrotik", partial(
        MikroTikDevice, timeout=timeout, known_hosts=known_hosts,
        export_read_timeout=export_read_timeout, export_retries=export_retries))
    DeviceFactory.register("frr", partial(
        FRRDevice, timeout=timeout, known_hosts=known_hosts, frr_shell=frr_shell))
