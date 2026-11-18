import shlex
from unittest.mock import Mock
import pytest
from core.models import DeviceInfo
from core.exceptions import DeviceCommandError, DeviceRestoreError
from devices.write_adapter import WriteSSHAdapter
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager


class FRRTransport:
    def __init__(self):
        self.description = None
        self.ip = '192.0.2.1/24'
        self.writes = []
        self.timeout_after_apply = False
        self.reject = False

    def config(self):
        desc = '' if self.description is None else ' description '+self.description+'\n'
        return ('Building configuration...\nCurrent configuration:\n!\nfrr version 8.2.2\n'
                'hostname frr\ninterface eth0\n'+desc+' ip address '+self.ip+'\nexit\n!\nend')

    def send_command(self, command, **kwargs):
        if 'show running-config' in command:
            return self.config()
        self.writes.append(command)
        if self.reject:
            return '% Unknown command'
        for part in shlex.split(command):
            if part.startswith('description '):
                self.description = part[12:]
            elif part == 'no description':
                self.description = None
        if self.timeout_after_apply:
            self.timeout_after_apply = False
            raise TimeoutError('already applied')
        return ''


@pytest.fixture
def router():
    d=WriteSSHAdapter(DeviceInfo('R3','192.0.2.3','frr'),frr_shell='linux')
    d._connection=FRRTransport()
    return d


@pytest.mark.parametrize('old',[None,'existing description'])
def test_frr_real_tv5_contract_and_restore_old_or_absent_description(router,tmp_path,old):
    router._connection.description=old
    backup=BackupManager(str(tmp_path))
    assert backup.backup(router).success
    snap=backup.list_snapshots('R3')[0]
    result=ConfigManager(backup_manager=backup).deploy(
        [router],'tv2_description',{'interface':'eth0','description':'TV2 test'})[0]
    assert result.success
    assert router._connection.description=='TV2 test'
    assert RestoreManager().restore(router,snap).success
    assert router._connection.description==old


def test_timeout_after_apply_rolls_back(router,tmp_path):
    router._connection.timeout_after_apply=True
    result=ConfigManager(backup_manager=BackupManager(str(tmp_path))).deploy(
        [router],'tv2_description',{'interface':'eth0','description':'test'})[0]
    assert not result.success and result.data['rolled_back']
    assert router._connection.description is None


def test_drift_is_not_partially_restored(router):
    baseline=router.get_running_config()
    router._connection.ip='192.0.2.99/24'
    with pytest.raises(DeviceRestoreError):router.restore_config(baseline)
    assert router._connection.writes==[]


@pytest.mark.parametrize('commands',[
    ['hostname changed'], ['interface eth0','description x; reboot','exit'],
    ['interface eth0','description x\nshutdown','exit'],
    ['interface eth0','ip address 10.0.0.1/24','exit'],
    ['interface eth99','description test','exit'],
])
def test_reject_unsupported_commands_before_write(router,commands):
    with pytest.raises(DeviceCommandError):router.push_config(commands)
    assert router._connection.writes==[]


def test_rejected_write_never_reports_success(router):
    router._connection.reject=True
    with pytest.raises(DeviceCommandError):
        router.push_config(['interface eth0','description test','exit'])


def test_normalizes_timestamp_without_changing_configuration():
    d=WriteSSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'))
    session=Mock()
    session.send_command.return_value='# 2026-11-17 10:00:00 by RouterOS 7.23.8\n/system identity set name=R1\n[admin@R1] >'
    d._connection=session
    assert d.get_running_config().rstrip()=='# RouterOS 7.23.8\n/system identity set name=R1'
    session.set_base_prompt.assert_called_once()
