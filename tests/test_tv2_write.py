import hashlib
from dataclasses import replace
from unittest.mock import Mock
import pytest
from core.models import DeviceInfo, TaskResult
from core.exceptions import DeviceCommandError, DeviceRestoreError
from devices.ssh_adapter import SSHAdapter
from devices.write_adapter import WriteSSHAdapter
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager
from services.verification import VerificationService


class RouterTransport:
    """SSH boundary double with independent router state and export formatting."""
    def __init__(self, platform):
        self.platform=platform; self.name='baseline'; self.address='192.0.2.10/24'
        self.writes=[]; self.fail_after_apply=False; self.ignore_write=False; self.tick=0
        self.prompt_name=self.name

    def set_base_prompt(self):
        self.prompt_name=self.name

    def config(self):
        self.tick+=1
        if self.platform=='mikrotik':
            return (f'# 2026-11-17 01:00:{self.tick%60:02} by RouterOS 7.23.8\n'
                    f'/ip address add address={self.address} interface=ether1\n'
                    f'/system identity set name={self.name}' +
                    (f'\n[admin@{self.name}] >' if self.prompt_name!=self.name else ''))
        return ('Building configuration...\n\nCurrent configuration:\n!\n'
                f'frr version 8.2.2\nhostname {self.name}\ninterface eth0\n'
                f' ip address {self.address}\nexit\n!\nend')

    def send_command(self, command, **kwargs):
        if command=='/export terse' or 'show running-config' in command:
            return self.config()
        self.writes.append(command)
        import re
        name=re.search(r'(?:name=|hostname )([A-Za-z][A-Za-z0-9_-]*)',command).group(1)
        if not self.ignore_write:self.name=name
        if self.fail_after_apply:
            self.fail_after_apply=False
            raise TimeoutError('transport interrupted after apply')
        return ''


@pytest.fixture(params=['mikrotik'])
def lab(request):
    d=WriteSSHAdapter(DeviceInfo('R1','192.0.2.10',request.param),frr_shell='linux')
    d._connection=RouterTransport(request.param)
    return d


def setup_manager(tmp_path):
    b=BackupManager(str(tmp_path/'backups'))
    return b,ConfigManager(backup_manager=b)


def test_full_backup_deploy_restore_preserves_other_config(lab,tmp_path):
    b,c=setup_manager(tmp_path)
    assert b.backup(lab).success
    baseline=b.list_snapshots('R1')[0]
    result=c.deploy([lab],'tv2_identity',{'identity_name':'changed'})[0]
    assert result.success and result.data['verified']
    assert lab._connection.name=='changed'
    restored=RestoreManager().restore(lab,baseline)
    assert restored.success and restored.data['exact_hash_match']
    assert lab._connection.name=='baseline'
    assert lab._connection.address=='192.0.2.10/24'


def test_failed_backup_never_writes(lab,tmp_path):
    b,c=setup_manager(tmp_path)
    b.backup=Mock(return_value=TaskResult('R1','backup',False,'failed'))
    r=c.deploy([lab],'tv2_identity',{'identity_name':'changed'})[0]
    assert not r.success and not r.data['push_started']
    assert not r.data['rollback_attempted'] and lab._connection.writes==[]


def test_partial_apply_timeout_rolls_back(lab,tmp_path):
    _,c=setup_manager(tmp_path)
    lab._connection.fail_after_apply=True
    r=c.deploy([lab],'tv2_identity',{'identity_name':'changed'})[0]
    assert not r.success and r.data['rollback_attempted'] and r.data['rolled_back']
    assert lab._connection.name=='baseline'


def test_verification_failure_is_not_success(lab,tmp_path):
    _,c=setup_manager(tmp_path)
    lab._connection.ignore_write=True
    r=c.deploy([lab],'tv2_identity',{'identity_name':'changed'})[0]
    assert not r.success and r.data['rollback_attempted'] and r.data['rolled_back']


def test_restore_rejects_unrelated_drift_before_write(lab,tmp_path):
    b,_=setup_manager(tmp_path);assert b.backup(lab).success
    baseline=b.list_snapshots('R1')[0]
    lab._connection.address='192.0.2.99/24'
    r=RestoreManager().restore(lab,baseline)
    assert not r.success and lab._connection.writes==[]
    assert lab._connection.address=='192.0.2.99/24'


@pytest.mark.parametrize('field,value',[('sha256','0'*64),('device_name','other'),('scope','unknown')])
def test_invalid_snapshot_rejected_before_write(lab,tmp_path,field,value):
    b,_=setup_manager(tmp_path);assert b.backup(lab).success
    snap=replace(b.list_snapshots('R1')[0],**{field:value})
    assert RestoreManager().restore(lab,snap).error_code=='INVALID_SNAPSHOT'
    assert lab._connection.writes==[]


def test_unknown_template_and_missing_variable_fail(lab,tmp_path):
    _,c=setup_manager(tmp_path)
    assert not c.dry_run([lab],'unknown',{})[0].success
    assert not c.dry_run([lab],'tv2_identity',{})[0].success
    assert lab._connection.writes==[]


def test_out_of_scope_template_never_writes(lab,tmp_path):
    b,c=setup_manager(tmp_path);b.backup=Mock(wraps=b.backup)
    r=c.deploy([lab],'ospf',{'networks':[]})[0]
    assert not r.success
    assert lab._connection.writes==[]


def test_old_readonly_adapter_stays_readonly():
    d=SSHAdapter(DeviceInfo('R1','192.0.2.10','mikrotik'))
    with pytest.raises(NotImplementedError):d.push_config(['anything'])
    with pytest.raises(NotImplementedError):d.restore_config('anything')


def test_write_rejects_command_injection(lab):
    prefix='/system identity set name=' if lab.info.platform=='mikrotik' else 'hostname '
    with pytest.raises(DeviceCommandError):lab.push_config([prefix+'safe; reboot'])
    assert lab._connection.writes==[]


def test_failed_rollback_is_reported(lab,tmp_path):
    _,c=setup_manager(tmp_path)
    lab._connection.fail_after_apply=True
    c.restore_manager.restore=Mock(return_value=TaskResult('R1','restore',False,'restore failed'))
    r=c.deploy([lab],'tv2_identity',{'identity_name':'changed'})[0]
    assert not r.success and r.data['rollback_attempted'] and not r.data['rolled_back']
    assert r.data['rollback_error']=='restore failed'
