"""Offline tests. Optional cross-branch worktrees contain unmodified services."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.models import DeviceInfo
from core.base import NetworkDevice
from core.factory import DeviceFactory
from core.exceptions import DeviceAuthenticationError, DeviceTimeoutError, DeviceCommandError, DeviceConnectionError
from devices.ssh_adapter import SSHAdapter, register_device_adapters
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException, ReadTimeout
from paramiko import BadHostKeyException

MT = '# 2026-11-09 12:00:00 by RouterOS 7.23.8\n/interface bridge add name=lab\n'
FRR = 'frr version 8.2.2\nfrr defaults traditional\ninterface eth0\n ip address 192.168.10.25/24\n!\nend\n'


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch('devices.ssh_adapter.ConnectHandler')
        self.connect = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.session = self.connect.return_value
        self.info = DeviceInfo('MT-R1', '192.168.10.21', 'mikrotik')

    def device(self, platform='mikrotik'):
        info = self.info if platform == 'mikrotik' else DeviceInfo('FRR-1','192.168.10.25','frr')
        return SSHAdapter(info, username='backup', password='private-value')

    def test_contract_factory_credentials(self):
        register_device_adapters()
        for platform in ['mikrotik','frr']:
            d = DeviceFactory.create(DeviceInfo('lab','192.0.2.1',platform))
            self.assertIsInstance(d, NetworkDevice)
            with patch('devices.ssh_adapter.credentials_from_env', return_value=Mock(username='backup',password='private-value')) as env:
                d.connect(); env.assert_called_once_with('lab'); d.disconnect()

    def test_mikrotik_config(self):
        self.session.send_command.return_value = MT
        with self.device() as d:
            self.assertEqual(d.info,self.info)
            self.assertEqual(d.get_running_config(),MT)
        self.assertEqual(self.session.send_command.call_args.args[0],'/export terse')
        self.assertTrue(self.connect.call_args.kwargs['ssh_strict'])
        self.session.disconnect.assert_called_once()

    def test_frr_linux(self):
        self.session.send_command.side_effect = ['FRRouting 8.2.2',FRR]
        with self.device('frr') as d:
            d.probe(); self.assertEqual(d.get_running_config(),FRR)
        self.assertEqual([c.args[0] for c in self.session.send_command.call_args_list],
                         ['vtysh -c "show version"','vtysh -c "show running-config"'])

    def test_vtysh_login(self):
        self.session.send_command.side_effect = ['% Unknown command: vtysh',FRR]
        with self.device('frr') as d: self.assertEqual(d.get_running_config(),FRR)

    def test_invalid_output_closes_session(self):
        for platform,output in [('mikrotik','failure: private-value'),('mikrotik','version: 7'),
                                ('frr','frr version 8.2.2\ninterface eth0'),('frr','sh: vtysh: not found'),('frr','')]:
            self.session.send_command.return_value = output
            d = self.device(platform); d.connect()
            with self.assertRaises(DeviceCommandError) as caught: d.get_running_config()
            self.assertNotIn('private-value',str(caught.exception))
            self.assertIsNone(d._connection)

    def test_auth_timeout_hostkey_errors(self):
        for exc,expected in [(NetmikoAuthenticationException('private-value'),DeviceAuthenticationError),
                             (NetmikoTimeoutException('private-value'),DeviceTimeoutError),
                             (BadHostKeyException('host',Mock(),Mock()),DeviceConnectionError)]:
            self.connect.side_effect = exc
            device = self.device()
            with self.assertRaises(expected) as caught:
                device.connect()
            self.assertNotIn('private-value',str(caught.exception))
            self.assertIsNone(device._connection)

    def test_read_timeout_cleanup(self):
        self.session.send_command.side_effect = ReadTimeout('private-value')
        with self.assertRaises(DeviceTimeoutError):
            with self.device() as d: d.get_running_config()
        self.session.disconnect.assert_called_once()

    def test_read_only(self):
        d = self.device()
        with self.assertRaises(NotImplementedError): d.push_config(['anything'])
        with self.assertRaises(NotImplementedError): d.restore_config('anything')
        with self.assertRaises(DeviceCommandError): d.send_command('/system reboot')
        self.connect.assert_not_called()

    def test_not_connected(self):
        with self.assertRaises(DeviceConnectionError): self.device().get_running_config()

    def test_tv4_services(self):
        root = os.environ.get('TV2_TV4_ROOT')
        if not root: self.skipTest('Set TV2_TV4_ROOT to TV4 checkout')
        import services
        services.__path__.insert(0,str(Path(root)/'services'))
        from services.backup_manager import BackupManager
        from services.change_detector import ChangeDetector
        from services.backup_scheduler import BackupScheduler
        for platform,content in [('mikrotik',MT),('frr',FRR)]:
            with tempfile.TemporaryDirectory() as directory:
                self.session.send_command.return_value = content
                manager = BackupManager(directory)
                with self.device(platform) as d:
                    self.assertTrue(manager.backup(d).success)
                    meta = json.loads(next(Path(directory).glob('*.json')).read_text())
                    raw = next(Path(directory).glob('*.cfg')).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),meta['sha256'])
                    self.assertFalse(ChangeDetector(manager).check(d).data['changed'])
                    self.session.send_command.return_value = content.replace('lab','lab2') if platform == 'mikrotik' else content.replace('.25','.26')
                    self.assertTrue(ChangeDetector(manager).check(d).data['changed'])
                self.assertTrue(BackupScheduler(manager).run_once([self.device(platform)])[0].success)

    def test_tv3_services(self):
        root = os.environ.get('TV2_TV3_ROOT')
        if not root: self.skipTest('Set TV2_TV3_ROOT to TV3 checkout')
        import services
        services.__path__.insert(0,str(Path(root)/'services'))
        from services.connection_manager import ConnectionManager
        register_device_adapters()
        with patch('devices.ssh_adapter.credentials_from_env',return_value=Mock(username='backup',password='private-value')):
            self.assertTrue(ConnectionManager(max_workers=1).run([self.info])[0].success)


if __name__ == '__main__': unittest.main()
