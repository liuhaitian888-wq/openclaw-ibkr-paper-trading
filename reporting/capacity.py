"""Bounded passive capacity evidence, owned by the existing secretary observer.

Only our fixed-size sampler state is replaced. Business DBs are opened mode=ro;
no checkpoint, maintenance, payload reads, retention or recovery operations.
"""
from contextlib import closing
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from .database_console import DATABASES, contained

GIB = 1024**3
INTERVAL = 300
MAX_SAMPLES = 288
MAX_BYTES = 1024**2
STALE_AFTER = 900
COUNTS = {
    'trading_audit.sqlite3': ('paper_readback_observations',),
    'financial_ledger.sqlite3': ('observations',),
    'runtime/recovery.sqlite3': ('paper_callback_events', 'module_events', 'runtime_health_samples'),
    'agent_secretary.sqlite3': ('secretary_events', 'screen_pool_projection'),
}
AUXILIARY_DATABASES = tuple('secretary-oauth/'+name for name in ('logs_2.sqlite', 'queue_1.sqlite', 'state_5.sqlite', 'memories_1.sqlite', 'goals_1.sqlite'))
BUCKETS = frozenset(('backups', 'runtime', 'migration-evidence', 'archives', 'engineering',
    'baseline-backups', 'reports', 'logs', 'screening', 'secretary-oauth', 'deployment-evidence'))
THRESHOLDS = dict(warning_free_fraction=.25, critical_free_fraction=.10,
    warning_free_bytes=8*GIB, critical_free_bytes=2*GIB,
    warning_days=7, critical_days=2, warning_db_bytes_day=512*1024**2,
    critical_db_bytes_day=GIB, warning_rows_day=100_000, critical_rows_day=1_000_000,
    warning_errors_hour=10, critical_errors_hour=60,
    warning_wal_bytes=64*1024**2, critical_wal_bytes=512*1024**2,
    recovery_samples=3, minimum_growth_span_seconds=3600)


def _load(root):
    path = contained(root, 'runtime/capacity.json')
    if not path.is_file():
        return {}
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Capacity state exceeds fixed budget')
    data = json.loads(path.read_text())
    if data.get('version') != 1 or not isinstance(data.get('samples'), list) or len(data['samples']) > MAX_SAMPLES:
        raise ValueError('Capacity state requires explicit reconciliation')
    return data


def tree_inventory(root, *, budget=.25, max_entries=20_000):
    """File metadata only. A partial scan never claims a complete total."""
    deadline = time.monotonic()+budget
    pending = [Path(root)]
    out = dict(complete=True, entries=0, allocated_bytes={}, sqlite_files={}, unregistered_sqlite=[], candidates_truncated=False, denied=0)
    while pending:
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    out['entries'] += 1
                    if out['entries'] > max_entries or time.monotonic() >= deadline:
                        out['complete'] = False
                        return out
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                            continue
                        st = entry.stat(follow_symlinks=False)
                        relative = Path(entry.path).relative_to(root)
                        bucket = relative.parts[0] if relative.parts[0] in BUCKETS else 'other'
                        sizes = out['allocated_bytes']
                        sizes[bucket] = sizes.get(bucket, 0) + getattr(st, 'st_blocks', 0)*512
                        if entry.name.endswith(('.sqlite3', '.sqlite', '.db')):
                            counts = out['sqlite_files']
                            counts[bucket] = counts.get(bucket, 0)+1
                            rel = relative.as_posix()
                            historical = bucket in ('backups','migration-evidence','archives','engineering','baseline-backups','deployment-evidence') or rel.startswith(('runtime/session-recovery/','runtime/notification-center-deployment/','runtime/paper-acceptance-deployment/'))
                            if not historical and rel not in {row[0] for row in DATABASES} and rel not in AUXILIARY_DATABASES:
                                if len(out['unregistered_sqlite']) < 32:
                                    out['unregistered_sqlite'].append(dict(path=rel, bytes=st.st_size, state='IDENTITY_REVIEW_REQUIRED'))
                                else:
                                    out['candidates_truncated'] = True
                    except OSError:
                        out['denied'] += 1
        except OSError:
            out['denied'] += 1
    out['complete'] = out['denied'] == 0
    return out


def database_sample(root, relative):
    out = dict(state='UNKNOWN', rows={})
    try:
        path = contained(root, relative)
        if not path.is_file():
            return dict(state='MISSING', rows={})
        st = path.stat()
        out.update(bytes=st.st_size, identity=[st.st_dev, st.st_ino])
        for suffix in ('wal', 'shm'):
            side = contained(root, relative+'-'+suffix)
            out[suffix+'_bytes'] = side.stat().st_size if side.is_file() else 0
        if relative in AUXILIARY_DATABASES:
            out['state']='STAT_ONLY_INTERNAL'
            return out
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.01)) as c:
            c.execute('PRAGMA query_only=ON')
            deadline = time.monotonic()+.08
            c.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            for name in ('page_size', 'page_count', 'freelist_count'):
                out[name] = c.execute('PRAGMA '+name).fetchone()[0]
            # Fixed table set, each count shares a single per-DB deadline.
            # Failure/lock is UNKNOWN, never zero. No ANALYZE or all-table count.
            for table in COUNTS.get(relative, ()):
                try:
                    out['rows'][table] = c.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]
                except sqlite3.Error:
                    out['rows'][table] = None
            if relative == 'runtime/recovery.sqlite3':
                try:
                    out['notification_error_events'] = c.execute("SELECT count(*) FROM notification_attempt_events WHERE stage IN ('PREFLIGHT_FAILED','REJECTED','UNKNOWN')").fetchone()[0]
                except sqlite3.Error:
                    out['notification_error_events'] = None
            out['state'] = 'OBSERVED'
    except (OSError, ValueError, sqlite3.Error):
        out['state'] = 'UNAVAILABLE'
    return out


def collect_sample(root, now):
    st = os.statvfs(root)
    return dict(at=now, filesystem=[os.stat(root).st_dev, st.f_blocks, st.f_frsize],
        total_bytes=st.f_blocks*st.f_frsize, available_bytes=st.f_bavail*st.f_frsize,
        free_fraction=st.f_bavail/st.f_blocks,
        databases={name: database_sample(root, name) for name in tuple(row[0] for row in DATABASES)+AUXILIARY_DATABASES})


def growth(samples):
    """Signed endpoint deltas, only across >=1h of continuous same-FS evidence."""
    unknown = dict(state='UNKNOWN', days_to_full=None, database_bytes_day={}, rows_day={}, errors_hour=None)
    if len(samples) < 3:
        return unknown
    last = samples[-1]
    valid = [last]
    for row in reversed(samples[:-1]):
        if row['filesystem'] != last['filesystem'] or not 0 < valid[-1]['at']-row['at'] <= STALE_AFTER:
            break
        valid.append(row)
    first = valid[-1]
    span = last['at']-first['at']
    if len(valid) < 3 or span < THRESHOLDS['minimum_growth_span_seconds']:
        return unknown
    rate = (first['available_bytes']-last['available_bytes'])/span
    result = dict(unknown, state='OBSERVED', span_seconds=span, filesystem_bytes_day=rate*86400,
        days_to_full=last['available_bytes']/rate/86400 if rate > 0 else None)
    for name, end in last['databases'].items():
        start = first['databases'].get(name, {})
        continuous = all(row['databases'].get(name, {}).get('identity') == end.get('identity')
                         and row['databases'].get(name, {}).get('state') in ('OBSERVED','STAT_ONLY_INTERNAL') for row in valid)
        if not continuous or end.get('identity') != start.get('identity'):
            continue
        result['database_bytes_day'][name] = ((end['bytes']+end['wal_bytes'])-(start['bytes']+start['wal_bytes']))/span*86400
        for table, count in end['rows'].items():
            old = start.get('rows', {}).get(table)
            if count is not None and old is not None and all(row['databases'][name]['rows'].get(table) is not None for row in valid):
                result['rows_day'][name+':'+table] = (count-old)/span*86400
        if name == 'runtime/recovery.sqlite3':
            counts = [row['databases'][name].get('notification_error_events') for row in valid]
            if all(type(value) is int for value in counts) and end['notification_error_events'] >= start['notification_error_events']:
                result['errors_hour'] = (end['notification_error_events']-start['notification_error_events'])/span*3600
    return result


def assess(samples, previous):
    last = samples[-1]
    rates = growth(samples)
    reasons = []
    level = 0
    def flag(rank, reason):
        nonlocal level
        level = max(level, rank)
        reasons.append(reason)
    for rank, prefix in ((1, 'warning'), (2, 'critical')):
        if last['free_fraction'] <= THRESHOLDS[prefix+'_free_fraction'] or last['available_bytes'] <= THRESHOLDS[prefix+'_free_bytes']:
            flag(rank, 'DISK_'+prefix.upper())
        if rates['days_to_full'] is not None and rates['days_to_full'] <= THRESHOLDS[prefix+'_days']:
            flag(rank, 'FORECAST_'+prefix.upper())
        if any(value >= THRESHOLDS[prefix+'_db_bytes_day'] for value in rates['database_bytes_day'].values()):
            flag(rank, 'DB_GROWTH_'+prefix.upper())
        if any(value >= THRESHOLDS[prefix+'_rows_day'] for value in rates['rows_day'].values()):
            flag(rank, 'ROW_GROWTH_'+prefix.upper())
        if rates['errors_hour'] is not None and rates['errors_hour'] >= THRESHOLDS[prefix+'_errors_hour']:
            flag(rank, 'NOTIFICATION_ERROR_EVENT_GROWTH_'+prefix.upper())
    for name, db in last['databases'].items():
        if db.get('wal_bytes', 0) >= THRESHOLDS['critical_wal_bytes']:
            flag(2, 'WAL_CRITICAL')
        elif len(samples) >= 3 and all(0 < b['at']-a['at'] <= STALE_AFTER for a,b in zip(samples[-3:],samples[-2:])) and all(row['databases'].get(name, {}).get('identity') == db.get('identity') and row['databases'].get(name, {}).get('wal_bytes', 0) >= THRESHOLDS['warning_wal_bytes'] for row in samples[-3:]):
            flag(1, 'WAL_PERSISTENT')
    if len(samples) >= 3 and all(any(row['databases'].get(name[0], {}).get('state') != 'OBSERVED' for name in DATABASES) for row in samples[-3:]):
        flag(1, 'METADATA_REPEATED_UNAVAILABLE')
    old = previous.get('level', 0)
    clear = 0
    if level < old:
        prefix = 'critical' if old == 2 else 'warning'
        headroom = (last['free_fraction'] > THRESHOLDS[prefix+'_free_fraction']+.03
                    and last['available_bytes'] > THRESHOLDS[prefix+'_free_bytes']+.5*GIB)
        continuous = len(samples) >= 2 and 0 < samples[-1]['at']-samples[-2]['at'] <= STALE_AFTER
        clear = (previous.get('clear_samples', 0) if continuous else 0)+1 if headroom else 0
        if clear < THRESHOLDS['recovery_samples']:
            level = old
            reasons.append('RECOVERY_HYSTERESIS')
    return dict(level=level, state=('OK', 'WARNING', 'CRITICAL')[level],
        clear_samples=clear, reasons=sorted(set(reasons)), growth=rates)


def public_status(item):
    """A fixed numeric view; never echo caller prose, paths or DB/account data."""
    if item.get('incident_key') != 'storage-capacity' or item.get('kind') not in ('ALERT', 'ESCALATION_RED', 'RECOVERY') and not item.get('kind', '').startswith('REMINDER_'):
        return None
    p = item.get('payload', {})
    if p.get('scope') != 'CAPACITY' or p.get('grants_trading_permission') is not False:
        return None
    value = p.get('capacity', {})
    if not isinstance(value, dict) or set(value) != {'total_bytes', 'available_bytes', 'days_to_full', 'level'}:
        return None
    if any(type(value.get(k)) is not int or not 0 <= value[k] <= 2**60 for k in ('total_bytes', 'available_bytes', 'level')):
        return None
    if value['total_bytes'] == 0 or value['available_bytes'] > value['total_bytes'] or value['level'] not in (0, 1, 2):
        return None
    days = value['days_to_full']
    if days is not None and (type(days) not in (int, float) or not math.isfinite(days) or not 0 <= days <= 1e9):
        return None
    return ('主机容量｜'+('正常', '预警', '严重')[value['level']]
        +f"\n可用 {value['available_bytes']/GIB:.2f} GiB / 总计 {value['total_bytes']/GIB:.2f} GiB"
        +'\n线性距满估计：'+(f'{days:.1f}天' if days is not None else 'UNKNOWN（证据不足或无正增长）')
        +'\n只作容量提示；保留历史副本，清理需逐项审核。')


def _publish(root, data):
    """Capacity transition/cursor are one existing DB transaction, crash safe.

    Snapshot is saved first; the next tick reconciles a missed outbox write even
    when a new sample is not due. Existing UNKNOWN deliveries are never replayed.
    """
    from .incidents import IncidentStore
    path = contained(root, 'runtime/recovery.sqlite3')
    if not path.is_file():
        raise FileNotFoundError('Existing recovery owner required')
    store = IncidentStore(path)
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT payload FROM incident_cursors WHERE source='capacity-v1'").fetchone()
        cursor = json.loads(row[0]) if row else dict(level=0, sequence=0)
        risk = data['risk']
        if cursor['level'] == risk['level']:
            return
        sequence = cursor['sequence']+1
        last = data['samples'][-1]
        payload = dict(scope='CAPACITY', severity=('GREEN', 'YELLOW', 'RED')[risk['level']],
            grants_trading_permission=False,
            reason='主机容量风险等级变化；详情请通过容量只读工具核对。',
            capacity={k: last[k] for k in ('total_bytes', 'available_bytes')})
        payload['capacity'].update(level=risk['level'], days_to_full=risk['growth']['days_to_full'])
        now = store.clock()
        payload.update(queued_at=now, incident_opened_at=now,
            private_notice=risk['level'] == 2, requires_response=risk['level'] == 2)
        if risk['level'] == 2:
            payload['reason'] = ('主机容量严重风险：可用'+f"{last['available_bytes']/GIB:.2f}"+
                ' GiB。请核对大产物和低优先写入，保护核心运行；不要删除活库、历史副本或UNKNOWN/回执。')
        encoded = json.dumps(payload, sort_keys=True)
        # Ordinary status belongs in the existing archive, never the delivery
        # queue. No OPEN incident is created, so generic reminders cannot turn
        # a passive warning into private/group notification spam.
        c.execute('INSERT INTO incident_events VALUES (?,?,?,?,?)',
            ('storage-capacity:'+str(sequence), 'storage-capacity', encoded, int(risk['level'] == 0), now))
        if risk['level'] == 2:
            c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,?,'ALERT',?,'PENDING')",
                ('storage-capacity', sequence, encoded))
        c.execute("INSERT OR REPLACE INTO incident_cursors VALUES('capacity-v1',?)",
                  (json.dumps(dict(level=risk['level'], sequence=sequence)),))


def _save(root, result):
    raw = json.dumps(result, separators=(',', ':'), allow_nan=False)
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError('Capacity state exceeds fixed budget')
    path = contained(root, 'runtime/capacity.json')
    temporary = contained(root, 'runtime/capacity.json.tmp')
    with temporary.open('w') as out:
        os.chmod(temporary, 0o600)
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def _reconcile_notification(root, data):
    if data.get('notification_pending'):
        _publish(root, data)
        data['notification_pending'] = False
        _save(root, data)


def tick(root, *, now=None):
    """Existing inbox owner calls this; no daemon or transport is created."""
    now = time.time() if now is None else now
    lock = contained(root, 'runtime/capacity.lock')
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        data = _load(root)
        samples = data.get('samples', [])
        if samples and 0 <= now-samples[-1]['at'] < INTERVAL:
            _reconcile_notification(root, data)
            return False
        if samples and now < samples[-1]['at']:
            raise ValueError('Capacity clock regression requires reconciliation')
        samples = (samples+[collect_sample(root, now)])[-MAX_SAMPLES:]
        risk = assess(samples, data.get('risk', {}))
        inventory = data.get('inventory', {})
        if not inventory or now-inventory.get('at', 0) >= 3600:
            inventory = dict(tree_inventory(root), at=now)
        result = dict(version=1, samples=samples, risk=risk, inventory=inventory)
        result['notification_pending'] = data.get('notification_pending', False) or risk['level'] != data.get('risk', {}).get('level', 0)
        _save(root, result)
        _reconcile_notification(root, result)
        from .recovery import RecoveryCoordinator
        complete = all(samples[-1]['databases'].get(name[0], {}).get('state') == 'OBSERVED' for name in DATABASES)
        coordinator=RecoveryCoordinator(contained(root, 'runtime/recovery.sqlite3'))
        coordinator.observe('CAPACITY', 'HEALTHY' if risk['level'] == 0 and complete else 'DEGRADED',
            freshness='FRESH', enabled=True, reason='Passive bounded capacity observation', capacity_state=risk['state'])
        from .storage_policy import observe as observe_budget
        try:
            observe_budget(root,coordinator)
        except (OSError,ValueError,TimeoutError):
            coordinator.observe('OPTIONAL_STORAGE_WRITES','DEGRADED',freshness='UNKNOWN',enabled=True,reason='Optional budget evidence unavailable; core capacity independent')
        return True


def read(root, *, now=None):
    """Secretary reads stored evidence only. Never creates files or scans DBs."""
    now = time.time() if now is None else now
    try:
        data = _load(root)
    except (OSError, ValueError, TypeError):
        return dict(state='UNKNOWN', reason='Capacity snapshot unavailable or invalid')
    if not data.get('samples'):
        return dict(state='NOT_OBSERVED', grants_trading_permission=False)
    latest = data['samples'][-1]
    age = now-latest['at']
    from .storage_policy import read as read_optional
    optional=read_optional(root)
    return dict(optional_write_budget=optional,state=data['risk']['state'] if 0 <= age <= STALE_AFTER else 'STALE',
        observed_at=latest['at'], age_seconds=age, latest=latest, risk=data['risk'],
        inventory=data['inventory'], sample_count=len(data['samples']), thresholds=THRESHOLDS,
        threshold_status='PROVISIONAL; calibrate growth after continuous evidence',
        suggestions=['核对新增大产物的预算、来源及副本哈希；先提交逐项回收候选，不执行清理',
            '对高频重复回调/健康样本评估语义去重和写入节流，保留订单、回执与UNKNOWN',
            'WAL异常先核对长读事务及连接owner，不自动checkpoint或重启'],
        limitations=['Endpoint linear estimate is not a guarantee; UNKNOWN is not zero growth',
            'Row counts cover fixed tables only and may be UNKNOWN under budget/lock',
            'Four registered business DBs plus fixed OAuth auxiliary DB metadata; auxiliary data is not a new SQL grant',
            'File metadata inventory is not live-DB identity, duplicate or restore verification',
            'No integrity check, checkpoint, VACUUM, cleanup or business permission'],
        grants_trading_permission=False)
