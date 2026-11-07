"""Consistent individual SQLite backups; restoring always requires reconciliation."""
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from reporting.journal_backup import backup_journal


def main():
    os.umask(0o077)
    root = Path.home() / '.local/state/openclaw'
    disk = os.statvfs(root)
    if disk.f_bavail / disk.f_blocks < .20:
        raise RuntimeError('Backup refused: less than 20% free disk')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    target = root / 'backups' / stamp
    target.mkdir(parents=True, mode=0o700)
    items = []
    for name in ('trading_audit.sqlite3', 'financial_ledger.sqlite3', 'runtime/recovery.sqlite3', 'agent_secretary.sqlite3'):
        source = root / name
        if not source.is_file():
            items.append(dict(source=name, status='MISSING_NOT_PUBLISHED'))
            continue
        raw = target / source.name
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(raw)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup SQLite quick_check failed: '+name)
        with raw.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        packed = raw.with_suffix(raw.suffix+'.gz')
        with raw.open('rb') as src, gzip.open(packed, 'wb', compresslevel=3) as dst:
            shutil.copyfileobj(src, dst)
        raw.unlink()  # Only this newly generated temporary copy, never a source.
        items.append(dict(source=name, status='BACKED_UP', sha256_uncompressed=digest,
                          file=packed.name, compressed_bytes=packed.stat().st_size))
    for name in ('production.json', 'delivery.json', 'PAUSED', 'runtime/MAINTENANCE', 'runtime/risk-controls.json', 'runtime/RISK_CONTROLS_REQUIRED', 'runtime/secretary-policy.json', 'runtime/research-universe.json', 'runtime/intelligence-policy.json', 'runtime/database-layout.json'):
        source = root / name
        if source.is_file():
            shutil.copy2(source, target / source.name)
    journals={name:backup_journal(root/'reports'/name/'history.jsonl', target/'journals'/name)
              for name in ('order_rejections','position_protection','position_guard')}
    manifest = dict(created_at=stamp, items=items, journals=journals, cross_database_atomic=False,
                    restore_requires_maintenance_and_broker_reconciliation=True,
                    production_state_published=(root/'production.json').is_file())
    with (target/'backup.json').open('w') as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
