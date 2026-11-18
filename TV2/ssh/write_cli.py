"""Explicit TV2 write entry point using the unchanged TV4/TV5 services.

Run from repository root: python -m TV2.ssh.write_cli --help
Credentials use the existing credential_ref environment contract.
"""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from devices.write_adapter import WriteSSHAdapter
from services.inventory import InventoryManager
from services.backup_manager import BackupManager
from services.config_manager import ConfigManager
from services.restore import RestoreManager


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','deploy','restore'])
    parser.add_argument('--inventory',required=True)
    parser.add_argument('--device',required=True,help='Exactly one device; no implicit all-device writes')
    parser.add_argument('--known-hosts',required=True)
    parser.add_argument('--backup-dir',default='backups/tv2-write')
    parser.add_argument('--template',choices=['tv2_identity','tv2_description'])
    parser.add_argument('--vars-file')
    parser.add_argument('--snapshot-id')
    parser.add_argument('--dry-run',action='store_true',help='Validate deploy commands without SSH')
    args=parser.parse_args(argv)
    if args.dry_run and args.action!='deploy':parser.error('--dry-run is only for deploy')
    os.umask(0o077)
    device=None
    try:
        matches=[d for d in InventoryManager(args.inventory).load() if d.name==args.device]
        if len(matches)!=1:raise ValueError('Expected one matching inventory device')
        device=WriteSSHAdapter(matches[0],known_hosts=args.known_hosts,frr_shell='linux')
        manager=ConfigManager()
        variables={}
        if args.action=='deploy':
            if not args.template or not args.vars_file:raise ValueError('Deploy requires --template and --vars-file')
            variables=json.loads(Path(args.vars_file).read_text())
            if not isinstance(variables,dict):raise ValueError('Template variables must be an object')
            rendered=manager.dry_run([device],args.template,variables)[0]
            if not rendered.success:raise ValueError('Template rendering failed')
            commands=[line.strip() for line in rendered.data['rendered_config'].splitlines()
                      if line.strip() and not line.lstrip().startswith(('#','!'))]
            device.validate_config_commands(commands)
            if args.dry_run:
                print(json.dumps({'device':args.device,'scope':device.write_scope,'commands':commands},ensure_ascii=False))
                return 0
        backup=BackupManager(args.backup_dir)
        snapshot=None
        if args.action=='restore':
            if not args.snapshot_id:raise ValueError('Restore requires explicit --snapshot-id')
            snapshot=next((s for s in backup.list_snapshots(args.device) if s.snapshot_id==args.snapshot_id),None)
            if snapshot is None:raise ValueError('Snapshot not found for selected device')
            if not RestoreManager().validate_snapshot(device,snapshot):raise ValueError('Invalid snapshot')
        device.connect()
        if args.action=='backup':result=backup.backup(device)
        elif args.action=='restore':result=RestoreManager(backup_manager=backup).restore(device,snapshot)
        else:result=ConfigManager(backup_manager=backup).deploy([device],args.template,variables)[0]
        print(json.dumps(asdict(result),ensure_ascii=False))
        return 0 if result.success else 1
    except (ValueError,OSError,KeyError) as exc:
        print(f'Input error: {exc}')
        return 2
    except Exception as exc:
        print(f'Operation failed: {type(exc).__name__}')
        return 1
    finally:
        if device is not None:device.disconnect()


if __name__=='__main__':raise SystemExit(main())
