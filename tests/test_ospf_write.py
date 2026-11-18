import json
from unittest.mock import Mock

import pytest

from core.exceptions import DeviceCommandError, DeviceRestoreError
from core.models import DeviceInfo
from devices.ospf_adapter import OSPFSSHAdapter, validate_variables
from devices.ssh_adapter import SSHAdapter, register_device_adapters
from core.factory import DeviceFactory
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager
from services.verification import VerificationService

MT = '# RouterOS 7.23.8\n/ip address add address=192.0.2.1/24 interface=ether1\n/system identity set name=R1'
FRR = 'frr version 8.2.2\nfrr defaults traditional\nhostname frr\n!\ninterface eth0\n ip address 192.0.2.3/24\nexit\n!\nend'
VARIABLES = {'router_id': '10.255.0.1', 'networks': [{'prefix': '192.0.2.0/24'}]}


def adapter(platform):
    return OSPFSSHAdapter(DeviceInfo('R1', '192.0.2.1', platform), frr_shell='linux')


def rendered(d, variables=VARIABLES):
    manager = ConfigManager()
    result = manager.dry_run([d], 'ospf', variables)[0]
    assert result.success
    return manager._commands(result.data['rendered_config'])


@pytest.mark.parametrize('platform', ['mikrotik', 'frr'])
def test_template_and_idempotent_redeploy(platform):
    d = adapter(platform)
    commands = rendered(d)
    assert not any('write memory' in x or '/routing ospf network' in x for x in commands)
    desired = d._requested(commands)
    d._send_write = Mock()
    d._replace(desired, desired)
    d._send_write.assert_not_called()


@pytest.mark.parametrize('variables', [
    {'networks': []},
    dict(VARIABLES, router_id='1.1.1.1; /system reboot'),
    dict(VARIABLES, router_id='0.0.0.0'),
    dict(VARIABLES, interfaces=[{'name': 'eth0', 'ip': '10.0.0.1/24'}]),
    dict(VARIABLES, networks=[{'prefix': '192.0.2.1/24'}]),
    dict(VARIABLES, networks=[{'prefix': '192.0.2.0/24', 'area_id': '0.0.0.1'}]),
    dict(VARIABLES, networks=[{'prefix': '192.0.2.0/24'}]*2),
])
def test_invalid_or_ignored_variables_are_rejected(variables):
    with pytest.raises(DeviceCommandError):
        validate_variables(variables)


@pytest.mark.parametrize('platform,content,extra', [
    ('mikrotik', MT, '/routing ospf instance add name=production router-id=1.1.1.1'),
    ('mikrotik', MT, '/routing ospf instance add name=tv2-ospf router-id=1.1.1.1 redistribute=connected'),
    ('frr', FRR, 'router ospf\n ospf router-id 1.1.1.1\n redistribute connected\nexit'),
    ('frr', FRR, 'interface eth1\n ip ospf area 0.0.0.0\nexit'),
])
def test_unsupported_existing_ospf_blocks_before_backup(tmp_path, platform, content, extra):
    d = adapter(platform)
    d._connection = Mock()
    d.get_running_config = Mock(return_value=(content+'\n'+extra if platform=='mikrotik' else content.replace('end', extra+'\nend')))
    d._send_write = Mock()
    manager = BackupManager(str(tmp_path))
    manager.backup = Mock()
    result = ConfigManager(backup_manager=manager).deploy([d], 'ospf', VARIABLES)[0]
    assert not result.success and not result.data['push_started']
    manager.backup.assert_not_called()
    d._send_write.assert_not_called()


@pytest.mark.parametrize('platform,content', [('mikrotik', MT), ('frr', FRR)])
def test_restore_empty_baseline_removes_created_ospf_but_not_other_settings(platform, content):
    d = adapter(platform)
    desired = d._requested(rendered(d))
    empty, rest = d._split(content)
    d._send_write = Mock()
    d._replace(desired, empty)
    sent = '\n'.join(call.args[0] for call in d._send_write.call_args_list)
    assert ('no router ospf' if platform=='frr' else 'instance remove') in sent
    assert 'write memory' not in sent and '/ip address' not in sent


@pytest.mark.parametrize('platform,content', [('mikrotik', MT), ('frr', FRR)])
def test_unmanaged_drift_blocks_restore(platform, content):
    d = adapter(platform)
    d._connection = Mock()
    d.get_running_config = Mock(return_value=content.replace('192.0.2.', '198.51.100.'))
    d._send_write = Mock()
    with pytest.raises(DeviceRestoreError):
        d.restore_config(content)
    d._send_write.assert_not_called()


def test_partial_routeros_write_is_restorable_after_timeout(tmp_path):
    d = adapter('mikrotik')
    state = [MT]
    d._connection = Mock()
    d.get_running_config = lambda: state[0]
    d._send_write = Mock()
    manager = BackupManager(str(tmp_path))
    assert manager.backup(d).success
    baseline = manager.list_snapshots('R1')[0]
    def write(command):
        if 'instance add' in command:
            state[0] += '\n'+command
            raise TimeoutError('simulated timeout after apply')
        if 'instance remove' in command:
            state[0] = MT
    d._send_write.side_effect = write
    result = ConfigManager(backup_manager=manager).deploy([d], 'ospf', VARIABLES)[0]
    assert not result.success and result.data['rolled_back']
    assert VerificationService().verify_config_match(d, baseline.content)['exact_hash_match']


def test_restore_verification_rejects_extra_ospf_network():
    d = adapter('frr')
    block = 'router ospf\n ospf router-id 1.1.1.1\n network 192.0.2.0/24 area 0.0.0.0\nexit\n'
    expected = FRR.replace('end', block+'end')
    d.get_running_config = Mock(return_value=expected.replace('exit\nend', ' network 198.51.100.0/24 area 0.0.0.0\nexit\nend'))
    assert not VerificationService().verify_config_match(d, expected)['passed']


def test_routeros_property_order_and_default_values_are_semantic_only():
    d = adapter('mikrotik')
    one = MT+'\n/routing ospf instance add name=tv2-ospf version=2 router-id=1.1.1.1'
    two = MT+'\n/routing ospf instance add disabled=no router-id=1.1.1.1 name=tv2-ospf'
    assert d.normalize_config_for_verification(one)==d.normalize_config_for_verification(two)
    with pytest.raises(DeviceCommandError):
        d.normalize_config_for_verification(two+' redistribute=static')


@pytest.mark.parametrize('platform,commands', [
    ('frr', ['router ospf', 'ospf router-id 1.1.1.1', 'write memory', 'exit']),
    ('frr', ['router ospf', 'ospf router-id 1.1.1.1', 'network 0.0.0.0/0 area 0.0.0.1', 'exit']),
    ('mikrotik', ['/system identity set name=oops']),
])
def test_scope_cannot_execute_unapproved_commands(platform, commands):
    with pytest.raises(DeviceCommandError):
        adapter(platform).validate_config_commands(commands)


def test_factory_requires_explicit_ospf_opt_in(monkeypatch):
    monkeypatch.setattr(DeviceFactory, '_registry', {})
    info = DeviceInfo('R1','192.0.2.1','frr')
    register_device_adapters()
    assert not isinstance(DeviceFactory.create(info), OSPFSSHAdapter)
    register_device_adapters(write=True, write_scope='ospf', frr_shell='linux')
    assert isinstance(DeviceFactory.create(info), OSPFSSHAdapter)


@pytest.mark.parametrize('states,passed', [
    ({'1.1.1.1':['Full/DR'], '2.2.2.2':['2-Way/DROther']}, True),
    ({'1.1.1.1':['2-Way/DROther'], '2.2.2.2':['2-Way/DROther']}, False),
    ({'1.1.1.1':['Full/DR']}, False),
    ({'1.1.1.1':['Full/DR'], '2.2.2.2':['ExStart']}, False),
])
def test_neighbor_convergence_requires_expected_peers_and_full_adjacency(states, passed):
    d=adapter('frr')
    d.ospf_neighbors=Mock(return_value=states)
    result=VerificationService().verify_ospf_convergence(d,['1.1.1.1','2.2.2.2'],timeout=.001)
    assert result['passed'] is passed


def test_selected_ospf_routes_required():
    d=adapter('frr')
    d.ospf_neighbors=Mock(return_value={'1.1.1.1':['Full/DR']})
    d.ospf_routes=Mock(return_value=['192.0.2.0/24'])
    result=VerificationService().verify_ospf_convergence(d,['1.1.1.1'],['198.51.100.0/24'],timeout=.001)
    assert not result['passed'] and result['missing_routes']==['198.51.100.0/24']


def test_no_neighbor_convergence_rolls_back_deploy(tmp_path):
    from services.verification import OSPFVerificationService
    from core.fake_device import FakeDevice
    d=FakeDevice(DeviceInfo('R1','192.0.2.1','frr'))
    d.connect()
    baseline=d.get_running_config()
    d.ospf_neighbors=Mock(return_value={})
    result=ConfigManager(backup_manager=BackupManager(str(tmp_path)),
                         verifier=OSPFVerificationService(['1.1.1.1'], .001)).deploy([d],'ospf',VARIABLES)[0]
    assert not result.success and result.data['rolled_back']
    assert d.get_running_config()==baseline


def test_cli_dry_run_ospf_and_missing_confirmation(tmp_path, monkeypatch, capsys):
    import cli
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([{'name':'R1','host':'192.0.2.1','platform':'mikrotik'}]))
    variables=tmp_path/'vars.json';variables.write_text(json.dumps(VARIABLES))
    monkeypatch.setattr(OSPFSSHAdapter,'connect',lambda self:pytest.fail('dry-run/cancel must not connect'))
    args=['--inventory',str(inventory),'deploy','--device','R1','--template','ospf',
          '--vars-file',str(variables),'--known-hosts','hosts','--write-scope','ospf']
    assert cli.main(args+['--dry-run'])==0
    assert 'interface-template' in capsys.readouterr().out
    assert cli.main(args)==2


def test_routeros_actual_export_omits_default_backbone_area_id():
    d=adapter('mikrotik')
    actual=MT+'\n/routing ospf instance add name=tv2-ospf router-id=10.255.0.1\n/routing ospf area add instance=tv2-ospf name=tv2-backbone\n/routing ospf interface-template add area=tv2-backbone comment=tv2-ospf-192-0-2-0-24 networks=192.0.2.0/24'
    assert d._split(actual)[0]==d._requested(rendered(d,dict(VARIABLES,router_id='10.255.0.1')))


@pytest.mark.parametrize('payload', [
    {'neighbors': {'1.1.1.1':[{'nbrState':'Full/DR'}]}},
    {'routerId':'2.2.2.2','neighbors': {'1.1.1.1':[{'nbrState':'Full/DR'}]}},
    {'1.1.1.1':[{'nbrState':'Full/DR'}]},
])
def test_frr_neighbor_json_wrapper(payload):
    d=adapter('frr');d.send_command=Mock(return_value=json.dumps(payload))
    assert d.ospf_neighbors()=={'1.1.1.1':['Full/DR']}


def test_routeros_route_flags_not_confused_with_comment():
    d=adapter('mikrotik')
    d.send_command=Mock(return_value='0 DAc comment=ospf dst-address=192.0.2.0/24\n1 DAo dst-address=198.51.100.0/24 gateway=192.0.2.2\n2 DIo dst-address=203.0.113.0/24')
    assert d.ospf_routes()==['198.51.100.0/24']


@pytest.mark.parametrize('platform,output,passed', [
    ('mikrotik','sent=3 received=3 packet-loss=0%', True),
    ('mikrotik','sent=3 received=2 packet-loss=33%', False),
    ('frr','3 packets transmitted, 3 packets received, 0% packet loss', True),
    ('frr','3 packets transmitted, 0 received, 100% packet loss', False),
])
def test_bounded_ping_requires_all_packets(platform,output,passed):
    d=adapter(platform);d._read=Mock(return_value=output)
    assert d.ping_ospf_target('192.0.2.1')['passed'] is passed
    with pytest.raises(DeviceCommandError):d.ping_ospf_target('192.0.2.1; reboot')


def test_frr_8_2_actual_neighbor_state_field():
    d=adapter('frr')
    d.send_command=Mock(return_value=json.dumps({'neighbors':{
        '10.255.0.1':[{'state':'Full/Backup','converged':'Full','role':'Backup'}],
        '10.255.0.4':[{'state':'2-Way/DROther','converged':'2-Way','role':'DROther'}]}}))
    assert d.ospf_neighbors()=={'10.255.0.1':['Full/Backup'],'10.255.0.4':['2-Way/DROther']}
