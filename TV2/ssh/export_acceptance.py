"""Read-only RouterOS export/Backup acceptance through ConnectionManager.

Repeats reads in one session and backups in fresh sessions. Reports contain
hashes, timing and sanitized phase metadata, never configuration or credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from core.factory import DeviceFactory
from core.models import TaskResult
from devices.ssh_adapter import register_device_adapters
from services.backup_manager import BackupManager
from services.connection_manager import ConnectionManager
from services.inventory import InventoryManager


def canonical_hash(content):
    content=re.sub(r'(?m)^# \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} by RouterOS (\S+)[ \t]*$',
                   r'# RouterOS \1',content)
    content='\n'.join(line.rstrip() for line in content.splitlines() if line.strip())
    return hashlib.sha256(content.encode()).hexdigest()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',required=True)
    p.add_argument('--device',action='append',required=True)
    p.add_argument('--known-hosts',required=True)
    p.add_argument('--iterations',type=int,default=20)
    p.add_argument('--export-read-timeout',type=float,default=30)
    p.add_argument('--export-retries',type=int,choices=(0,1),default=1)
    p.add_argument('--backup-dir',default='backups/export-acceptance')
    p.add_argument('--report-dir',default='reports/export-acceptance')
    args=p.parse_args(argv)
    if not 1<=args.iterations<=100 or not math.isfinite(args.export_read_timeout) or args.export_read_timeout<=0:
        p.error('iterations must be 1..100 and export timeout positive/finite')
    by_name={info.name:info for info in InventoryManager(args.inventory).load()}
    if set(args.device)-by_name.keys():p.error('Unknown device')
    infos=[by_name[name] for name in dict.fromkeys(args.device)]
    if any(info.platform!='mikrotik' for info in infos):p.error('Select RouterOS devices only')
    os.umask(0o077)
    folder=Path(args.report_dir);folder.mkdir(parents=True,exist_ok=True)
    dest=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    report={'real_ssh':True,'read_only':True,'export_read_timeout':args.export_read_timeout,
            'export_retries':args.export_retries,'reads':[],'backups':[],'success':False}
    previous=dict(DeviceFactory._registry)
    backup=BackupManager(args.backup_dir)
    def read_many(device):
        records=[]
        for number in range(1,args.iterations+1):
            started=time.monotonic()
            record={'device':device.info.name,'round':number,'success':False}
            try:
                device.connect()
                content=device.get_running_config()
                record.update(success=True,bytes=len(content.encode()),canonical_sha256=canonical_hash(content))
            except Exception as exc:
                record['error_code']=type(exc).__name__
            record.update(seconds=round(time.monotonic()-started,3),export_diagnostics=device.export_diagnostics)
            records.append(record)
        return TaskResult(device.info.name,'export_acceptance',all(r['success'] for r in records),
                          'Repeated exports completed',data={'records':records})
    def save_backup(device):
        started=time.monotonic()
        result=backup.backup(device)
        result.data.update(seconds=round(time.monotonic()-started,3),export_diagnostics=device.export_diagnostics)
        if result.success:
            snapshot=next(s for s in backup.list_snapshots(device.info.name) if s.snapshot_id==result.data['snapshot_id'])
            result.data['canonical_sha256']=canonical_hash(snapshot.content)
        return result
    try:
        register_device_adapters(known_hosts=args.known_hosts,export_read_timeout=args.export_read_timeout,
                                 export_retries=args.export_retries)
        manager=ConnectionManager(max_workers=min(4,len(infos)))
        for result in manager.run(infos,read_many):
            report['reads'].extend(result.data.get('records',[]))
            if not result.success:report.setdefault('errors',[]).append(result.error_code or 'READ_FAILED')
        dest.write_text(json.dumps(report,indent=2))
        print('Same-session reads:',sum(r['success'] for r in report['reads']),'/',len(report['reads']),flush=True)
        for number in range(1,args.iterations+1):
            for result in manager.run(infos,save_backup):
                report['backups'].append({'device':result.device,'round':number,'success':result.success,
                    'error_code':result.error_code,**{key:value for key,value in result.data.items()
                    if key in ('snapshot_id','seconds','export_diagnostics','canonical_sha256')}})
            dest.write_text(json.dumps(report,indent=2))
            print('Fresh-session backup round',number,'complete',flush=True)
        records=report['reads']+report['backups']
        report['stable_config']={info.name:len({r.get('canonical_sha256') for r in records if r['device']==info.name})==1
                                 for info in infos}
        report['success']=(len(report['reads'])==len(report['backups'])==args.iterations*len(infos)
                           and all(r['success'] for r in records) and all(report['stable_config'].values())
                           and not report.get('errors'))
    finally:
        DeviceFactory._registry.clear();DeviceFactory._registry.update(previous)
        dest.write_text(json.dumps(report,indent=2))
    print('Report:',dest,'PASS' if report['success'] else 'FAIL',flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
