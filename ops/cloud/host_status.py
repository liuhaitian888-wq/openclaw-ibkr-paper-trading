"""Collect local evidence only. No broker calls, notifications or recovery actions."""
from datetime import datetime, timezone
from contextlib import closing
import sqlite3
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.runtime_history import record
from scripts.production_health import smoke
from trading.production_paths import STATE_ROOT


def main():
    result = smoke()
    units = ('ibkr-display', 'ibkr-vnc', 'ibkr-web-vnc', 'ibkr-gateway', 'ibkr-paper-safety', 'ibkr-notifications', 'ibkr-readback', 'ibkr-heartbeat.timer')
    services = {}
    service_details = {}
    for unit in units:
        p = subprocess.run(['systemctl', 'is-active', unit], capture_output=True,
                           text=True, timeout=5)
        services[unit] = p.stdout.strip() or 'unknown'
        detail = subprocess.run(['systemctl', 'show', unit, '--property=UnitFileState,Result'],
                                capture_output=True, text=True, timeout=5)
        fields = dict(line.split('=', 1) for line in detail.stdout.splitlines() if '=' in line)
        service_details[unit] = dict(unit_file_state=fields.get('UnitFileState', 'unknown'),
                                     result=fields.get('Result', 'unknown'))
    disk = os.statvfs(STATE_ROOT)
    payload = dict(observed_at=datetime.now(timezone.utc).isoformat(),
                   services=services, service_details=service_details, smoke=result,
                   disk_free_fraction=disk.f_bavail / disk.f_blocks,
                   broker_authentication='UNVERIFIED_UNTIL_PAPER_READBACK')
    now=datetime.now(timezone.utc).timestamp()
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    states={'cloud.host':'OBSERVED_RUNNING'}
    states.update({'cloud.'+k:v for k,v in services.items()})
    with closing(sqlite3.connect(STATE_ROOT/'runtime/recovery.sqlite3',timeout=5)) as c,c:
        record(c,'host-status',boot,now,states,dict(services=service_details,disk_free_fraction=payload['disk_free_fraction']))
    path = STATE_ROOT / 'runtime/cloud-status.json'
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        json.dump(payload, handle, indent=2)
    temporary.replace(path)
    print(json.dumps(dict(overall=result['overall'], services=services,
                         paused=result['details']['paused'])))


if __name__ == '__main__':
    main()
