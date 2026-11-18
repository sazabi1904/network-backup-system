from dataclasses import replace
from threading import Event, Thread
from unittest.mock import Mock
import json
import pytest
import cli
from core.fake_device import FakeDevice
from core.models import DeviceInfo, TaskResult
from core.exceptions import DeviceWriteError
from core.operation_lock import device_operation
from core.factory import DeviceFactory
from devices.ssh_adapter import SSHAdapter, register_device_adapters
from devices.write_adapter import WriteSSHAdapter
from services.backup_manager import BackupManager
from services.restore import RestoreManager
from services.config_manager import ConfigManager
from services.verification import VerificationService
from tests.test_tv2_frr_write import FRRTransport


def fake():
    d=FakeDevice(DeviceInfo('R1','192.0.2.1','mikrotik'))
    d.connect()
    return d


@pytest.mark.parametrize('suffix',['\n/unexpected set enabled=yes','\n/system identity set name=WRONG'])
def test_restore_must_reject_extra_configuration(tmp_path,suffix):
    d=fake();b=BackupManager(str(tmp_path));assert b.backup(d).success
    snap=b.list_snapshots('R1')[0]
    d.restore_config=Mock(return_value=True)
    d.get_running_config=Mock(return_value=snap.content+suffix)
    result=RestoreManager().restore(d,snap)
    assert not result.success and result.error_code=='RESTORE_VERIFY_FAILED'


def test_restore_preserves_context_and_order():
    d=fake()
    expected='interface eth0\n description lab\nexit\ninterface eth1\nexit'
    d.get_running_config=Mock(return_value='interface eth0\nexit\ninterface eth1\n description lab\nexit')
    assert not VerificationService().verify_config_match(d,expected)['passed']


@pytest.mark.parametrize('field,value',[('device_name','other'),('sha256','0'*64)])
def test_invalid_snapshot_never_calls_restore(tmp_path,field,value):
    d=fake();b=BackupManager(str(tmp_path));b.backup(d)
    snap=replace(b.list_snapshots('R1')[0],**{field:value})
    d.restore_config=Mock()
    assert RestoreManager().restore(d,snap).error_code=='INVALID_SNAPSHOT'
    d.restore_config.assert_not_called()


def test_readonly_preflight_no_backup_no_rollback(tmp_path):
    d=SSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'))
    b=BackupManager(str(tmp_path));b.backup=Mock()
    r=ConfigManager(backup_manager=b).deploy([d],'tv2_identity',{'identity_name':'new'})[0]
    assert not r.success and not r.data['push_started'] and not r.data['rollback_attempted']
    b.backup.assert_not_called()


def frr():
    d=WriteSSHAdapter(DeviceInfo('R3','192.0.2.3','frr'),frr_shell='linux')
    d._connection=FRRTransport()
    return d


def test_backup_before_restore_failure_blocks_write(tmp_path):
    d=frr();b=BackupManager(str(tmp_path));b.backup(d);snap=b.list_snapshots('R3')[0]
    d._connection.description='changed'
    b.backup=Mock(return_value=TaskResult('R3','backup',False,'disk full'))
    r=RestoreManager(backup_manager=b).restore(d,snap)
    assert not r.success and d._connection.writes==[]


def test_delete_description_verifies_actual_absence():
    d=frr();d._connection.description='old'
    commands=['interface eth0','no description','exit']
    d.push_config(commands)
    assert VerificationService().verify_commands_present(d,commands)['passed']


@pytest.mark.parametrize('response,code',[
    ('failure: permission denied SECRET','WRITE_PERMISSION_DENIED'),
    ('% Unknown command SECRET','WRITE_REJECTED'),
    (TimeoutError('SECRET'),'WRITE_TIMEOUT'),
    (OSError('SECRET'),'WRITE_CONNECTION_LOST')])
def test_sanitized_write_errors_and_partial_state(response,code):
    d=frr();d._connection=Mock()
    if isinstance(response,Exception):d._connection.send_command.side_effect=response
    else:d._connection.send_command.return_value=response
    with pytest.raises(DeviceWriteError) as caught:d._send_write('safe-command')
    assert caught.value.code==code and caught.value.may_have_applied
    assert 'SECRET' not in str(caught.value)


def test_operation_lock_blocks_parallel_write_and_allows_nested_rollback():
    d=frr();held=Event();release=Event()
    def hold():
        with device_operation(d):held.set();release.wait(5)
    thread=Thread(target=hold);thread.start();assert held.wait(2)
    try:
        with pytest.raises(RuntimeError,match='active'):
            with device_operation(d):pass
    finally:release.set();thread.join()
    with device_operation(d):
        with device_operation(d):pass


def test_factory_write_mode_explicit_and_cli_restores_registry(monkeypatch):
    monkeypatch.setattr(DeviceFactory,'_registry',{})
    register_device_adapters()
    before=dict(DeviceFactory._registry)
    register_device_adapters(write=True,frr_shell='linux')
    assert isinstance(DeviceFactory.create(DeviceInfo('R1','192.0.2.1','mikrotik')),WriteSSHAdapter)
    DeviceFactory._registry=before.copy()
    monkeypatch.setattr(cli.ConnectionManager,'run',Mock(side_effect=RuntimeError('interrupt')))
    with pytest.raises(RuntimeError):cli._run_on_devices([],None,False,write=True)
    assert DeviceFactory._registry==before


def test_shared_cli_requires_confirmation_before_connect(tmp_path,monkeypatch):
    inv=tmp_path/'inventory.json';inv.write_text(json.dumps([{'name':'R1','host':'192.0.2.1','platform':'mikrotik'}]))
    monkeypatch.setattr(WriteSSHAdapter,'connect',lambda self:pytest.fail('must not connect'))
    assert cli.main(['--inventory',str(inv),'restore','--device','R1','--write-scope','managed',
                     '--known-hosts','hosts','--snapshot-id','x'])==2


def test_permissive_custom_verifier_cannot_accept_extra_config(tmp_path):
    d=fake();b=BackupManager(str(tmp_path));b.backup(d);snap=b.list_snapshots('R1')[0]
    d.restore_config=Mock(return_value=True)
    d.get_running_config=Mock(return_value=snap.content+'\n/extra setting=yes')
    verifier=Mock();verifier.verify_config_match.return_value={'passed':True}
    assert not RestoreManager(verifier=verifier).restore(d,snap).success


def test_menu_cancel_never_executes_live_write(monkeypatch):
    import main
    answers=iter(['inventory.json','R1','hosts','backups','snapshot-id','HUY'])
    monkeypatch.setattr('builtins.input',lambda prompt='':next(answers))
    monkeypatch.setattr(cli,'main',lambda args:pytest.fail('Canceled action must not run'))
    main._tv5_live('restore')


def test_restore_normalizes_metadata_but_keeps_snapshot_hash(tmp_path):
    from tests.test_tv2_write import RouterTransport
    d=WriteSSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'))
    d._connection=RouterTransport('mikrotik')
    b=BackupManager(str(tmp_path));b.backup(d);snap=b.list_snapshots('R1')[0]
    original_hash=snap.sha256
    assert RestoreManager(backup_manager=b).restore(d,snap).success
    assert snap.sha256==original_hash


def test_real_verification_does_not_expose_config_secrets():
    d=frr();baseline=d.get_running_config()
    d.get_running_config=Mock(return_value=baseline+'\npassword TOPSECRET')
    result=VerificationService().verify_config_match(d,baseline)
    assert not result['passed'] and result['unexpected_line_count']==1
    assert 'TOPSECRET' not in str(result)
