"""Offline tests; do not claim these establish connectivity to a real router."""
import unittest
from unittest.mock import patch, Mock
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout
from ssh_client import RouterSSH, RouterSSHError, main


class SSHTests(unittest.TestCase):
    def router(self, platform="mikrotik"):
        return RouterSSH("192.0.2.1", platform, "lab", "private-test-value")

    @patch("ssh_client.ConnectHandler")
    def test_auth_error_has_no_secret(self, connect):
        connect.side_effect = NetmikoAuthenticationException("private-test-value")
        with self.assertRaises(RouterSSHError) as caught:
            self.router().connect()
        self.assertNotIn("private-test-value", str(caught.exception))

    @patch("ssh_client.ConnectHandler")
    def test_network_timeout(self, connect):
        connect.side_effect = NetmikoTimeoutException("raw details")
        with self.assertRaisesRegex(RouterSSHError, "timed out"):
            self.router().connect()

    @patch("ssh_client.ConnectHandler")
    def test_read_timeout_still_disconnects(self, connect):
        connect.return_value.send_command_timing.side_effect = ReadTimeout("raw details")
        with self.assertRaises(RouterSSHError):
            with self.router() as router:
                router.probe()
        connect.return_value.disconnect.assert_called_once()

    @patch("ssh_client.ConnectHandler")
    def test_frr_shell_error_is_not_success(self, connect):
        connect.return_value.send_command_timing.return_value = "sh: show: not found"
        with self.assertRaisesRegex(RouterSSHError, "vtysh"):
            with self.router("frr") as router:
                router.probe()

    @patch("ssh_client.ConnectHandler")
    def test_both_platform_probes(self, connect):
        for platform, output in [("mikrotik", "version: 7.23.8"), ("frr", "FRRouting 8.2.2")]:
            session = Mock()
            session.send_command_timing.return_value = output
            connect.return_value = session
            with self.router(platform) as router:
                self.assertEqual(router.probe(), output)
            self.assertTrue(connect.call_args.kwargs["ssh_strict"])
            session.disconnect.assert_called_once()

    def test_requires_connection_and_valid_port(self):
        with self.assertRaises(RouterSSHError):
            self.router().probe()
        with self.assertRaises(ValueError):
            RouterSSH("host", "mikrotik", "lab", "", port=0)


if __name__ == "__main__":
    unittest.main()
