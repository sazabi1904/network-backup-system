"""Real OSPF config, neighbor/route convergence, restore and rollback acceptance.

Credentials use credential_ref environment variables. All selected devices are
restored in finally, and reports omit config contents and credentials.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from core.operation_lock import device_operation
from devices.ospf_adapter import OSPFSSHAdapter, validate_variables
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.inventory import InventoryManager
from services.restore import RestoreManager
from services.verification import VerificationService
from TV2.ssh.acceptance import ControlledFailure


def run(infos, plans, known_hosts, backup_dir, timeout=90, export_read_timeout=None, export_retries=1):
    devices = [OSPFSSHAdapter(info, known_hosts=known_hosts, frr_shell='linux',
                              export_read_timeout=export_read_timeout, export_retries=export_retries) for info in infos]
    backup = BackupManager(backup_dir)
    restore = RestoreManager(backup_manager=backup)
    verifier = VerificationService()
    records = {d.info.name: {'device': d.info.name, 'real_ssh': True, 'scope': d.write_scope,
                            'success': False} for d in devices}
    baselines = {}
    try:
        with ExitStack() as stack:
            for d in devices:
                stack.enter_context(device_operation(d))
            try:
                # Validate every target before the first device is modified.
                ids = [plans[d.info.name]['variables']['router_id'] for d in devices]
                if len(ids) != len(set(ids)):
                    raise ValueError('Router IDs must be unique')
                for d in devices:
                    plan = plans[d.info.name]
                    validate_variables(plan['variables'])
                    if not plan.get('expected_neighbors'):
                        raise ValueError('Each target requires expected_neighbors')
                    d.connect()
                    result = ConfigManager().dry_run([d], 'ospf', plan['variables'])[0]
                    if not result.success:
                        raise RuntimeError('Dry-run failed')
                    d.validate_config_commands(ConfigManager._commands(result.data['rendered_config']))
                    saved = backup.backup(d)
                    if not saved.success:
                        raise RuntimeError('Baseline backup failed')
                    baselines[d.info.name] = next(s for s in backup.list_snapshots(d.info.name)
                                                 if s.snapshot_id == saved.data['snapshot_id'])
                    records[d.info.name]['baseline_id'] = saved.data['snapshot_id']
                for d in devices:
                    record = records[d.info.name]
                    variables = plans[d.info.name]['variables']
                    manager = ConfigManager(backup_manager=backup, restore_manager=restore)
                    result = manager.deploy([d], 'ospf', variables)[0]
                    record['deploy'] = asdict(result)
                    if not result.success:
                        raise RuntimeError('Deploy failed on '+d.info.name)
                    before = d.get_running_config()
                    record['idempotent_deploy'] = asdict(manager.deploy([d], 'ospf', variables)[0])
                    if not record['idempotent_deploy']['success'] or not verifier.verify_config_match(d, before)['passed']:
                        raise RuntimeError('Idempotent deploy failed')
                    print(d.info.name, 'deploy/idempotence PASS', flush=True)
                for d in devices:
                    plan = plans[d.info.name]
                    result = verifier.verify_ospf_convergence(d, plan['expected_neighbors'],
                                                            plan.get('expected_routes', []), timeout)
                    records[d.info.name]['convergence'] = result
                    if not result['passed']:
                        raise RuntimeError('OSPF convergence failed on '+d.info.name)
                    probes = [d.ping_ospf_target(address) for address in plan.get('ping_targets', [])]
                    records[d.info.name]['data_plane'] = probes
                    if not all(probe['passed'] for probe in probes):
                        raise RuntimeError('OSPF data-plane probe failed on '+d.info.name)
                    print(d.info.name, 'neighbors/routes PASS', flush=True)
                for d in devices:
                    # Exercise changing/removing a network and rollback to a NONEMPTY OSPF snapshot.
                    variables = dict(plans[d.info.name]['variables'])
                    variables['networks'] = [{'prefix': '198.18.255.0/24'}]
                    before = d.get_running_config()
                    manager = ConfigManager(backup_manager=backup, restore_manager=restore,
                                            verifier=ControlledFailure())
                    result = manager.deploy([d], 'ospf', variables)[0]
                    record = records[d.info.name]
                    record['controlled_failure'] = asdict(result)
                    record['after_rollback'] = verifier.verify_config_match(d, before)
                    if result.success or not result.data.get('rolled_back') or not record['after_rollback']['passed']:
                        raise RuntimeError('Rollback failed on '+d.info.name)
                    print(d.info.name, 'nonempty OSPF rollback PASS', flush=True)
                for d in devices:
                    plan = plans[d.info.name]
                    result = verifier.verify_ospf_convergence(d, plan['expected_neighbors'],
                                                            plan.get('expected_routes', []), timeout)
                    records[d.info.name]['after_rollback_convergence'] = result
                    if not result['passed']:
                        raise RuntimeError('Post-rollback convergence failed on '+d.info.name)
                    records[d.info.name]['success'] = True
            finally:
                for d in reversed(devices):
                    if d.info.name in baselines:
                        try:
                            result = restore.restore(d, baselines[d.info.name])
                            records[d.info.name]['restore'] = asdict(result)
                            if not result.success:
                                records[d.info.name]['success'] = False
                            print(d.info.name, 'baseline restore', 'PASS' if result.success else 'FAIL', flush=True)
                        except Exception as exc:
                            records[d.info.name].update(success=False, recovery_error=type(exc).__name__)
    except Exception as exc:
        print('Acceptance failed:', type(exc).__name__, str(exc), flush=True)
        for record in records.values():
            record.update(success=False, error_type=type(exc).__name__)
    finally:
        for d in devices:
            try:
                d.disconnect()
            except Exception as exc:
                records[d.info.name].update(success=False, disconnect_error=type(exc).__name__)
    return list(records.values())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', required=True)
    p.add_argument('--plan', required=True, help='JSON mapping device names to variables/expected_neighbors/expected_routes')
    p.add_argument('--known-hosts', required=True)
    p.add_argument('--backup-dir', default='backups/ospf-acceptance')
    p.add_argument('--report-dir', default='reports/ospf-acceptance')
    p.add_argument('--convergence-timeout', '--timeout', dest='timeout', type=float, default=90,
                   help='OSPF convergence seconds; --timeout retained for compatibility')
    p.add_argument('--export-read-timeout', type=float)
    p.add_argument('--export-retries', type=int, choices=(0, 1), default=1)
    p.add_argument('--confirm-write', action='store_true', required=True)
    args = p.parse_args(argv)
    if not 0 < args.timeout <= 600:
        p.error('timeout must be in (0, 600]')
    os.umask(0o077)
    plans = json.loads(Path(args.plan).read_text())
    infos = InventoryManager(args.inventory).load()
    selected = [info for info in infos if info.name in plans]
    if not plans or set(plans) != {info.name for info in selected}:
        p.error('Plan must contain existing, unique inventory device names')
    records = run(selected, plans, args.known_hosts, args.backup_dir, args.timeout,
                  args.export_read_timeout, args.export_retries)
    folder = Path(args.report_dir)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    dest.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print('Report:', dest)
    return 0 if all(r['success'] for r in records) else 1


if __name__ == '__main__':
    raise SystemExit(main())
