"""RouterOS export recovery at the SSH boundary, without retrying writes."""
import json
from unittest.mock import Mock
import pytest
from netmiko.exceptions import ReadTimeout, NetmikoAuthenticationException
from core.exceptions import DeviceCommandError, DeviceTimeoutError, DeviceConnectionError, DeviceAuthenticationError, DeviceWriteError
from core.factory import DeviceFactory
from core.models import DeviceInfo, TaskResult
from devices.ssh_adapter import SSHAdapter, register_device_adapters
from devices.write_adapter import WriteSSHAdapter
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager

CONFIG = '# RouterOS 7.23.8\n/system identity set name=R1\n'


def session(host='R1', outcome=None):
    value=Mock()
    value.set_base_prompt.return_value=f'[admin@{host}]'
    if isinstance(outcome, BaseException):
        value.send_command.side_effect=outcome
    else:
        value.send_command.return_value=outcome if outcome is not None else CONFIG+f'[admin@{host}] >'
    return value


def adapter(monkeypatch, sessions, **options):
    connect=Mock(side_effect=sessions)
    monkeypatch.setattr('devices.ssh_adapter.ConnectHandler',connect)
    d=SSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'),username='admin',password='test-only',
                 known_hosts='verified_hosts',**options)
    d.connect()
    return d,connect


def test_retry_uses_fresh_transport_and_prompt_after_pattern_timeout(monkeypatch,caplog):
    first=session(outcome=ReadTimeout('Pattern not detected PRIVATE_CONFIG'))
    second=session('R1.new+')
    d,connect=adapter(monkeypatch,[first,second],timeout=9,export_read_timeout=75)
    assert d.get_running_config()==CONFIG
    first.disconnect.assert_called_once()
    assert connect.call_count==2
    for call in connect.call_args_list:
        assert call.kwargs['ssh_strict'] is True
        assert call.kwargs['alt_key_file']=='verified_hosts'
        assert call.kwargs['conn_timeout']==9
    options=second.send_command.call_args.kwargs
    assert options['read_timeout']==75 and options['cmd_verify'] is True
    assert options['auto_find_prompt'] is False and options['strip_prompt'] is False
    assert r'R1\.new\+' in options['expect_string']
    assert [x['phase'] for x in d.export_diagnostics]==['output_prompt','complete']
    assert 'PRIVATE_CONFIG' not in caplog.text
    d.disconnect();second.disconnect.assert_called_once()


@pytest.mark.parametrize('failure,phase',[
    (ReadTimeout('The command echo was not detected PRIVATE'),'command_echo'),
    (ReadTimeout('Pattern not detected PRIVATE'),'output_prompt'),
    (ReadTimeout('PRIVATE'),'export_read'),
])
def test_second_timeout_stops_and_exposes_only_safe_metadata(monkeypatch,caplog,failure,phase):
    one,two=session(outcome=failure),session(outcome=failure)
    d,connect=adapter(monkeypatch,[one,two])
    with pytest.raises(DeviceTimeoutError) as caught:d.get_running_config()
    assert connect.call_count==2 and d._connection is None
    assert caught.value.code=='EXPORT_TIMEOUT'
    assert len(caught.value.diagnostics)==2
    assert all(item['phase']==phase for item in caught.value.diagnostics)
    assert 'PRIVATE' not in str(caught.value) and 'PRIVATE' not in caplog.text
    one.disconnect.assert_called_once();two.disconnect.assert_called_once()


@pytest.mark.parametrize('failure',[EOFError('PRIVATE'),OSError('PRIVATE')])
def test_transport_loss_reconnects_only_once(monkeypatch,failure):
    d,connect=adapter(monkeypatch,[session(outcome=failure),session()])
    assert d.get_running_config()==CONFIG and connect.call_count==2
    assert d.export_diagnostics[0]['code']=='EXPORT_CONNECTION_LOST'
    d.disconnect()


def test_auth_failure_during_reconnect_is_not_retried(monkeypatch):
    d,connect=adapter(monkeypatch,[session(outcome=ReadTimeout('PRIVATE')),NetmikoAuthenticationException('PRIVATE')])
    with pytest.raises(DeviceAuthenticationError) as caught:d.get_running_config()
    assert connect.call_count==2 and caught.value.code=='EXPORT_AUTH_FAILED'
    assert caught.value.diagnostics[-1]['phase']=='reconnect'


def test_prompt_refresh_timeout_has_its_own_phase(monkeypatch):
    one=session();one.set_base_prompt.side_effect=ReadTimeout('PRIVATE')
    d,_=adapter(monkeypatch,[one,session()])
    assert d.get_running_config()==CONFIG
    one.send_command.assert_not_called()
    assert d.export_diagnostics[0]['phase']=='prompt_refresh'
    d.disconnect()


@pytest.mark.parametrize('raw',[
    CONFIG,
    CONFIG+'[admin@OTHER] >',
    CONFIG+'#error exporting "/routing/ospf" (timeout) PRIVATE\n[admin@R1] >',
    CONFIG+'  # error exporting "/ip/address" (timeout)\n[admin@R1] >',
    '# RouterOS 7.23.8\n[admin@R1] >',
    'PRIVATE\n[admin@R1] >',
])
def test_incomplete_export_never_creates_snapshot_or_retries(monkeypatch,tmp_path,raw):
    transport=session(outcome=raw)
    d,connect=adapter(monkeypatch,[transport])
    result=BackupManager(str(tmp_path)).backup(d)
    assert not result.success and result.error_code=='DeviceCommandError'
    assert list(tmp_path.iterdir())==[] and connect.call_count==1
    assert d._connection is None and 'PRIVATE' not in json.dumps(d.export_diagnostics)


def test_failed_pre_restore_export_never_sends_restore(monkeypatch,tmp_path):
    d,connect=adapter(monkeypatch,[session(),session(outcome=ReadTimeout()),session(outcome=ReadTimeout())])
    backup=BackupManager(str(tmp_path));saved=backup.backup(d)
    snapshot=next(s for s in backup.list_snapshots('R1') if s.snapshot_id==saved.data['snapshot_id'])
    d.disconnect();d.connect()
    d.write_scopes=('identity',)
    d.restore_config=Mock()
    result=RestoreManager(backup_manager=backup).restore(d,snapshot)
    assert not result.success and connect.call_count==3
    d.restore_config.assert_not_called()
    assert len(backup.list_snapshots('R1'))==1


def test_export_failure_blocks_deploy_before_write(monkeypatch,tmp_path):
    d,connect=adapter(monkeypatch,[session(outcome=ReadTimeout()),session(outcome=ReadTimeout())])
    d.write_scopes=('identity',)
    d.push_config=Mock()
    result=ConfigManager(backup_manager=BackupManager(str(tmp_path))).deploy([d],'tv2_identity',{'identity_name':'new'})[0]
    assert not result.success and not result.data['push_started']
    d.push_config.assert_not_called()


def test_write_timeout_is_never_automatically_replayed():
    d=WriteSSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'))
    d.get_running_config=Mock(return_value=CONFIG)
    d._connection=session(outcome=TimeoutError('PRIVATE'))
    with pytest.raises(DeviceWriteError):d.push_config(['/system identity set name=new'])
    d._connection.send_command.assert_called_once()
    assert d._connection.send_command.call_args.args[0]=='/system identity set name=new'


def test_other_read_commands_do_not_use_export_retry(monkeypatch):
    d,connect=adapter(monkeypatch,[session(outcome=ReadTimeout())])
    with pytest.raises(DeviceTimeoutError):d.send_command('/system resource print')
    assert connect.call_count==1 and d.export_diagnostics==[]


def test_retry_can_be_disabled(monkeypatch):
    d,connect=adapter(monkeypatch,[session(outcome=ReadTimeout())],export_retries=0)
    with pytest.raises(DeviceTimeoutError):d.get_running_config()
    assert connect.call_count==1


@pytest.mark.parametrize('kwargs',[
    {'export_read_timeout':0},{'export_read_timeout':float('nan')},
    {'export_read_timeout':float('inf')},{'export_read_timeout':-1},
    {'export_retries':2},{'export_retries':-1},{'export_retries':True},
])
def test_invalid_options_fail_before_connect(kwargs):
    with pytest.raises(ValueError):SSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'),**kwargs)


def test_factory_and_cli_forward_separate_export_options(monkeypatch,tmp_path):
    import cli
    monkeypatch.setattr(DeviceFactory,'_registry',{})
    register_device_adapters(export_read_timeout=75,export_retries=0)
    d=DeviceFactory.create(DeviceInfo('R1','192.0.2.1','mikrotik'))
    assert d.export_read_timeout==75 and d.export_retries==0
    inv=tmp_path/'inventory.json';inv.write_text(json.dumps([{'name':'R1','host':'192.0.2.1','platform':'mikrotik'}]))
    capture={}
    def run(infos,operation,demo,**options):
        capture.update(options)
        return [TaskResult('R1','deploy',True,'test-only')]
    monkeypatch.setattr(cli,'_run_on_devices',run)
    assert cli.main(['--inventory',str(inv),'deploy','--device','R1','--template','ospf',
                     '--backup-dir',str(tmp_path/'backups'),'--write-scope','ospf','--known-hosts','hosts',
                     '--confirm-write','--export-read-timeout','75','--export-retries','0'])==0
    assert capture['export_read_timeout']==75 and capture['export_retries']==0


def test_real_netmiko_prompt_reader_accepts_pattern_and_keeps_complete_export():
    # Exercise Netmiko's actual read_until_pattern, which wraps regexes in a
    # capturing group. Global inline flags fail there on Python 3.13.
    from netmiko import ConnectHandler
    conn=ConnectHandler(device_type='mikrotik_routeros',host='192.0.2.1',
                        username='test',password='test-only',auto_connect=False)
    conn.clear_buffer=Mock(return_value='')
    conn.write_channel=Mock()
    conn.read_channel=Mock(return_value='\r\n[admin@R1] >')
    conn.command_echo_read=Mock(return_value='/export terse\n'+CONFIG+'[admin@R1] >')
    conn.disconnect=Mock()
    d=SSHAdapter(DeviceInfo('R1','192.0.2.1','mikrotik'),export_retries=0)
    d._connection=conn
    assert d.get_running_config()==CONFIG
    assert d.export_diagnostics[-1]['phase']=='complete'
    assert conn.command_echo_read.call_args.kwargs['read_timeout']==10
    d.disconnect()


@pytest.mark.parametrize('value',['0','-1','nan','inf'])
def test_cli_rejects_invalid_export_timeout_before_connect(monkeypatch,value):
    import cli
    monkeypatch.setattr(cli,'_run_on_devices',lambda *a,**kw:pytest.fail('must not connect'))
    assert cli.main(['deploy','--device','R1','--template','ospf','--write-scope','ospf',
                     '--known-hosts','hosts','--confirm-write','--export-read-timeout',value])==2
