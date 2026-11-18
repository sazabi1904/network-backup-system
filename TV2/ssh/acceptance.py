"""Repeatable real-SSH acceptance of the explicitly supported TV2/TV5 scope."""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from datetime import datetime, timezone
from devices.write_adapter import WriteSSHAdapter
from core.operation_lock import device_operation
from services.inventory import InventoryManager
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager
from services.verification import VerificationService


class ControlledFailure(VerificationService):
    def verify_commands_present(self, device, commands):
        actual = super().verify_commands_present(device, commands)
        if not actual.get('passed'):
            return actual
        return {'passed':False, 'actual_change_verified':True, 'reason':'controlled rollback test'}


def run_device(device, manager, rollback=False, interface='eth0'):
    record={'device':device.info.name,'platform':device.info.platform,'scope':device.write_scope,
            'rollback_test':rollback,'success':False,'real_ssh':True}
    baseline=None
    restored=False
    restore=RestoreManager(backup_manager=manager)
    try:
        with device_operation(device):
            try:
                device.connect()
                device.probe()
                record['probe_success']=True
                template='tv2_identity' if device.info.platform=='mikrotik' else 'tv2_description'
                variables={'identity_name':'TV2RestoreCheck','interface':interface,'description':'TV2 restore acceptance'}
                config=ConfigManager(backup_manager=manager, restore_manager=restore,
                                     verifier=ControlledFailure() if rollback else None)
                rendered=config.dry_run([device],template,variables)[0]
                if not rendered.success:raise RuntimeError('Dry-run failed')
                device.validate_config_commands(config._commands(rendered.data['rendered_config']))
                saved=manager.backup(device)
                if not saved.success:raise RuntimeError('Baseline backup failed')
                baseline=next(s for s in manager.list_snapshots(device.info.name)
                              if s.snapshot_id==saved.data['snapshot_id'])
                record['baseline_id']=baseline.snapshot_id
                result=config.deploy([device],template,variables)[0]
                record['deploy']=asdict(result)
                if rollback:
                    if result.success or not result.data.get('rolled_back'):
                        raise RuntimeError('Expected controlled failure and verified rollback')
                    check=VerificationService().verify_config_match(device,baseline.content)
                    record['after_rollback']={'passed':check['passed'],'exact_hash_match':check.get('exact_hash_match')}
                    restored=check['passed']
                else:
                    if not result.success:raise RuntimeError('Deploy failed')
                    result=restore.restore(device,baseline)
                    record['restore']=asdict(result)
                    restored=result.success
                if not restored:raise RuntimeError('Baseline not verified')
                record['success']=True
            finally:
                if baseline is not None and not restored:
                    record['recovery']=asdict(restore.restore(device,baseline))
    except Exception as exc:
        record['error_type']=type(exc).__name__
    finally:
        try:device.disconnect()
        except Exception as exc:
            record.update(success=False,disconnect_error=type(exc).__name__)
    return record


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',required=True)
    p.add_argument('--device',action='append',required=True)
    p.add_argument('--known-hosts',required=True)
    p.add_argument('--backup-dir',default='backups/tv2-acceptance')
    p.add_argument('--report-dir',default='reports/tv2-acceptance')
    p.add_argument('--interface',default='eth0')
    p.add_argument('--rollback-check',action='store_true')
    p.add_argument('--confirm-write',action='store_true',required=True)
    args=p.parse_args(argv)
    os.umask(0o077)
    infos=InventoryManager(args.inventory).load()
    by_name={info.name:info for info in infos}
    if set(args.device)-by_name.keys():p.error('Unknown inventory device')
    manager=BackupManager(args.backup_dir)
    records=[]
    folder=Path(args.report_dir);folder.mkdir(parents=True,exist_ok=True)
    filename=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'
    for name in dict.fromkeys(args.device):
        d=WriteSSHAdapter(by_name[name],known_hosts=args.known_hosts,frr_shell='linux')
        result=run_device(d,manager,args.rollback_check,args.interface)
        records.append(result)
        (folder/filename).write_text(json.dumps(records,ensure_ascii=False,indent=2))
        print(name,'PASS' if result['success'] else 'FAIL',flush=True)
    print('Report:',folder/filename)
    return 0 if all(r['success'] for r in records) else 1


if __name__=='__main__':raise SystemExit(main())
