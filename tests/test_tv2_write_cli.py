import json
import pytest
from TV2.ssh.write_cli import main
from devices.write_adapter import WriteSSHAdapter
from core.factory import DeviceFactory


@pytest.fixture
def inputs(tmp_path):
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([{'name':'R1','host':'192.0.2.1','platform':'mikrotik'}]))
    variables=tmp_path/'vars.json'
    variables.write_text(json.dumps({'identity_name':'new-name'}))
    return ['--inventory',str(inventory),'--device','R1','--known-hosts',str(tmp_path/'known_hosts'),
            '--backup-dir',str(tmp_path/'backups')],variables


def test_dry_run_validates_without_connecting_or_changing_registry(inputs,monkeypatch,capsys):
    args,variables=inputs
    before=dict(DeviceFactory._registry)
    monkeypatch.setattr(WriteSSHAdapter,'connect',lambda self:pytest.fail('Unexpected connection'))
    assert main(['deploy',*args,'--template','tv2_identity','--vars-file',str(variables),'--dry-run'])==0
    assert 'new-name' in capsys.readouterr().out
    assert DeviceFactory._registry==before


def test_injection_rejected_before_connect(inputs,monkeypatch):
    args,variables=inputs
    variables.write_text(json.dumps({'identity_name':'safe; reboot'}))
    monkeypatch.setattr(WriteSSHAdapter,'connect',lambda self:pytest.fail('Unexpected connection'))
    assert main(['deploy',*args,'--template','tv2_identity','--vars-file',str(variables)])==1


def test_restore_requires_explicit_snapshot_before_connect(inputs,monkeypatch):
    args,_=inputs
    monkeypatch.setattr(WriteSSHAdapter,'connect',lambda self:pytest.fail('Unexpected connection'))
    assert main(['restore',*args])==2
