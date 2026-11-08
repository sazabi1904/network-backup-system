"""SSH probe for MikroTik RouterOS and FRR's vtysh login shell."""
import argparse
import getpass
import os
import sys
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout
from paramiko import SSHException


class RouterSSHError(Exception):
    """Safe error message suitable for displaying without credentials."""


class RouterSSH:
    DRIVERS = {"mikrotik": "mikrotik_routeros", "frr": "linux"}
    # Fixed read-only probes: FRR appliance logs directly into vtysh, not bash.
    COMMANDS = {"mikrotik": "/system resource print", "frr": "show version"}

    def __init__(self, host, platform, username, password, port=22, timeout=15):
        if platform not in self.DRIVERS:
            raise ValueError("Platform must be mikrotik or frr")
        if not host or not username or not 1 <= port <= 65535 or timeout <= 0:
            raise ValueError("Invalid host, username, port or timeout")
        self.platform = platform
        self._connection = None
        self._params = dict(host=host, device_type=self.DRIVERS[platform],
                            username=username, password=password, port=port,
                            conn_timeout=timeout, auth_timeout=timeout,
                            banner_timeout=timeout, ssh_strict=True,
                            system_host_keys=True, allow_agent=False, use_keys=False)
        self.timeout = timeout

    def connect(self):
        if self._connection is not None:
            return
        try:
            self._connection = ConnectHandler(**self._params)
        except NetmikoAuthenticationException:
            raise RouterSSHError("SSH authentication failed; check the account and password.") from None
        except NetmikoTimeoutException:
            raise RouterSSHError("SSH timed out; check host routing, port and SSH service.") from None
        except (SSHException, OSError):
            raise RouterSSHError("SSH failed; check the verified host key and SSH service.") from None

    def probe(self):
        if self._connection is None:
            raise RouterSSHError("Connect before running the probe.")
        try:
            output = self._connection.send_command_timing(
                self.COMMANDS[self.platform], read_timeout=self.timeout,
                strip_prompt=True, strip_command=True)
        except (ReadTimeout, NetmikoTimeoutException):
            raise RouterSSHError("Connected, but the device did not return output in time.") from None
        except (SSHException, OSError, EOFError):
            raise RouterSSHError("SSH connection was interrupted while reading output.") from None
        # Reject a Linux shell / unsupported CLI instead of reporting false success.
        marker = "version:" if self.platform == "mikrotik" else "FRRouting"
        if not isinstance(output, str) or marker not in output:
            raise RouterSSHError("Unexpected CLI output; FRR requires a vtysh login shell.")
        return output

    def disconnect(self):
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.disconnect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


def main():
    parser = argparse.ArgumentParser(description="SSH read-only probe for TV2 routers")
    parser.add_argument("--host", required=True)
    parser.add_argument("--platform", required=True, choices=RouterSSH.DRIVERS)
    parser.add_argument("--username", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    password = os.environ.get("TV2_SSH_PASSWORD")
    if password is None:
        password = getpass.getpass("SSH password: ")
    try:
        with RouterSSH(args.host, args.platform, args.username, password,
                       args.port, args.timeout) as router:
            output = router.probe()
        print(output)
        print("PASS: SSH authenticated and device version output verified.")
        return 0
    except (RouterSSHError, ValueError):
        # Print only our own safe diagnostics, never raw library exceptions.
        print(str(sys.exc_info()[1]), file=sys.stderr)
        return 1
    except (SSHException, OSError, EOFError):
        print("SSH transport or disconnect failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
