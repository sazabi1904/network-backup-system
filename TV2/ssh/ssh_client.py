"""CLI and compatibility import for the canonical read-only adapter."""
import argparse
import getpass
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.models import DeviceInfo
from core.exceptions import NetworkAutomationError
from devices.ssh_adapter import SSHAdapter, register_device_adapters

RouterSSH = SSHAdapter


def main():
    parser = argparse.ArgumentParser(description="TV2 SSH probe and config validation")
    parser.add_argument("--host", required=True)
    parser.add_argument("--name", default="lab-router")
    parser.add_argument("--platform", choices=["mikrotik", "frr"], required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--known-hosts")
    parser.add_argument("--frr-shell", choices=["auto", "linux", "vtysh"], default="auto")
    args = parser.parse_args()
    password = os.environ.get("TV2_SSH_PASSWORD")
    if password is None:
        password = getpass.getpass("SSH password: ")
    try:
        info = DeviceInfo(args.name, args.host, args.platform, port=args.port)
        with SSHAdapter(info, username=args.username, password=password,
                        timeout=args.timeout, known_hosts=args.known_hosts,
                        frr_shell=args.frr_shell) as device:
            device.probe()
            config = device.get_running_config()
        print(f"PASS: probe and config validated; {len(config.encode('utf-8'))} bytes")
        return 0
    except (NetworkAutomationError, ValueError):
        print("FAIL: " + str(sys.exc_info()[1]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
