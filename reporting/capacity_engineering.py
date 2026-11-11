"""Deterministic host incidents, not native instructions or model authority."""
from contextlib import closing
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import time

from .database_console import contained

SCOPE = 'capacity-followup-v1'
MAX_TASKS = 128
BATCH = 8


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _connect(path, *, readonly=False):
    if not path.is_file(): raise FileNotFoundError('Existing registered database required')
    c = sqlite3.connect(path.as_uri()+'?mode=ro' if readonly else str(path), uri=readonly, timeout=.01)
    try:
        deadline = time.monotonic()+.1
        c.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16384)
        c.execute('PRAGMA foreign_keys=ON')
        if readonly: c.execute('PRAGMA query_only=ON')
    except BaseException:
        c.close(); raise
    return c


def _owned_path(root, relative):
    path = contained(root,relative)  # Rejects symlinks along the whole relative path.
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('Cursor must be an unlinked regular file')
    return path


def _cursor(root):
    p = _owned_path(root, 'runtime/capacity-engineering.json')
    if not p.exists(): return {'version': 1, 'through_sequence': 0, 'active_sequence':0, 'state': 'BACKLOG'}
    if p.stat().st_size > 4096: raise ValueError('Cursor budget exceeded')
    value = json.loads(p.read_text())
    if value.get('version') != 1 or type(value.get('through_sequence')) is not int or not 0 <= value['through_sequence'] < 2**31:
        raise ValueError('Cursor requires reconciliation')
    active = value.get('active_sequence')
    if type(active) is not int or not 0 <= active <= value['through_sequence']:
        raise ValueError('Active incident identity requires reconciliation')
    return value


def _save(root, value):
    raw = _encode(value).encode()
    if len(raw) > 4096: raise ValueError('Cursor budget exceeded')
    target = _owned_path(root, 'runtime/capacity-engineering.json')
    temp = _owned_path(root, 'runtime/capacity-engineering.tmp')
    fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        meta = os.fstat(f.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1: raise ValueError('Cursor alias refused')
        os.ftruncate(f.fileno(),0)
        os.fchmod(f.fileno(), 0o600); f.write(raw); f.flush(); os.fsync(f.fileno())
    temp.replace(target)


def _source(c, sequence):
    event_id = 'storage-capacity:'+str(sequence)
    row = c.execute('SELECT payload,resolved,observed FROM incident_events WHERE event_id=? AND incident_key=?',
                    (event_id, 'storage-capacity')).fetchone()
    if row is None or len(row[0].encode()) > 8192: raise ValueError('Missing or oversized source occurrence')
    value = json.loads(row[0]); level = value.get('capacity', {}).get('level')
    if value.get('scope') != 'CAPACITY' or type(level) is not int or level not in (0,1,2):
        raise ValueError('Unrecognized capacity occurrence')
    if level != 2: return level, None
    capacity = value['capacity']
    if (value.get('severity') != 'RED' or value.get('private_notice') is not True
            or value.get('requires_response') is not True or value.get('grants_trading_permission') is not False
            or row[1] != 0 or type(row[2]) not in (int,float) or not math.isfinite(row[2])
            or set(capacity) != {'level','total_bytes','available_bytes','days_to_full'}
            or any(type(capacity[k]) is not int for k in ('total_bytes','available_bytes'))
            or not 0 <= capacity['available_bytes'] <= capacity['total_bytes'] or capacity['total_bytes'] <= 0
            or capacity['days_to_full'] is not None and (type(capacity['days_to_full']) not in (int,float)
                or not math.isfinite(capacity['days_to_full']) or capacity['days_to_full'] < 0)):
        raise ValueError('Invalid severe source evidence')
    wire = c.execute("SELECT id,payload FROM notification_outbox WHERE incident_key='storage-capacity' AND generation=? AND kind='ALERT'", (sequence,)).fetchone()
    if wire is None or wire[1] != row[0]: raise ValueError('Source event/outbox mismatch')
    # Only fixed numeric evidence crosses into the engineering prompt surface.
    return level, {'scope': SCOPE, 'source_event': event_id, 'source_sha256': hashlib.sha256(row[0].encode()).hexdigest(),
        'notification_id': wire[0], 'source_observed_at': row[2], 'capacity_at_event': capacity,
        'title': '主机容量风险诊断', 'observation': '真实严重容量事件已归档；当前水位须另查新鲜快照。',
        'suggested_change': '只读核对增长归属、可选写入预算和已有缓解证据；变更交既有工程owner。',
        'evidence': [event_id, 'notification-outbox:'+str(wire[0])],
        'authority': 'SYSTEM_CAPACITY_EVENT_READ_ONLY_FOLLOWUP', 'grants_model_execution': False,
        'grants_deployment_permission': False, 'grants_trading_permission': False,
        'grants_cleanup_permission': False, 'desktop_chat_wakeup_connected': False}


def _queue(root, sequence, payload):
    task = 'capacity-followup:'+str(sequence); encoded = _encode(payload); now = time.time()
    with closing(_connect(contained(root, 'agent_secretary.sqlite3'))) as c, c:
        c.execute('BEGIN IMMEDIATE')
        prior = c.execute('SELECT payload FROM secretary_engineering_tasks WHERE id=?', (task,)).fetchone()
        if prior:
            if prior[0] != encoded: raise ValueError('Task occurrence content conflict')
            return
        rows = c.execute("SELECT id FROM secretary_engineering_tasks WHERE id GLOB 'capacity-followup:*' LIMIT ?", (MAX_TASKS,)).fetchall()
        if len(rows) >= MAX_TASKS: raise ValueError('Protected task budget full; reconcile without deletion')
        c.execute("INSERT INTO secretary_engineering_tasks VALUES (?,?,?,'QUEUED_READ_ONLY',?,'{}',?,?)",
                  (task, payload['source_event'], SCOPE, encoded, now, now))
        c.execute('INSERT INTO secretary_events VALUES (?,?,?,?,?,?,?)',
                  (task, 'der-secretary', 'SYSTEM', 'ENGINEERING_PROPOSAL', None, encoded, now))
        c.execute('INSERT INTO secretary_events VALUES (?,?,?,?,?,?,?)',
                  (task+':queued', 'der-secretary', 'SYSTEM', 'ENGINEERING_STATUS', task,
                   _encode({'state':'QUEUED_READ_ONLY','task_id':task,'automatic_deployment':False}), now))


def reconcile(root):
    """Original capacity lock owns this bounded, idempotent cross-DB handoff."""
    if not contained(root, 'agent_secretary.sqlite3').is_file(): return {'state':'NOT_CONFIGURED'}
    try: prior = _cursor(root)
    except (OSError, ValueError, TypeError): return {'state':'BLOCKED','error':'CURSOR_RECONCILIATION_REQUIRED'}
    result = dict(prior)
    try:
        with closing(_connect(contained(root, 'runtime/recovery.sqlite3'), readonly=True)) as c:
            row = c.execute("SELECT payload FROM incident_cursors WHERE source='capacity-v1'").fetchone()
            head = json.loads(row[0])['sequence'] if row else 0
            if type(head) is not int or not result['through_sequence'] <= head < 2**31:
                raise ValueError('Source sequence regression')
            for sequence in range(result['through_sequence']+1, min(head, result['through_sequence']+BATCH)+1):
                level, payload = _source(c, sequence)
                if level == 0: result['active_sequence'] = 0
                elif payload:
                    active = result['active_sequence'] or sequence
                    if active != sequence:
                        _, payload = _source(c,active)
                        if payload is None: raise ValueError('Active severe source lost')
                    _queue(root, active, payload)
                    result['active_sequence'] = active
                result['through_sequence'] = sequence
            result = {'version':1, 'through_sequence':result['through_sequence'],
                      'active_sequence':result['active_sequence'],
                      'state':'CURRENT' if result['through_sequence'] == head else 'BACKLOG'}
        if result != prior: _save(root, result)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        result.update(state='BLOCKED', error=type(exc).__name__)
        # Keep the committed destination; cursor can safely retry exact identities.
        try: _save(root, result)
        except (OSError,ValueError): pass
    return result


def read(root):
    """Passive bounded queue view; never initializes databases or reconciles."""
    result = {'state':'NOT_CONFIGURED', 'items':[], 'desktop_chat_wakeup_connected':False,
              'automatic_model_execution':False, 'automatic_deployment':False}
    p = contained(root, 'agent_secretary.sqlite3')
    if not p.is_file(): return result
    try:
        result['handoff'] = _cursor(root)
        with closing(_connect(p, readonly=True)) as c:
            rows = c.execute("SELECT id,state,payload,native FROM secretary_engineering_tasks WHERE id GLOB 'capacity-followup:*' ORDER BY created DESC LIMIT 12").fetchall()
        for task, state, raw, native in rows:
            if len(raw.encode()) > 4096: raise ValueError('Task payload budget exceeded')
            payload = json.loads(raw)
            if payload.get('scope') != SCOPE: raise ValueError('Task scope conflict')
            result['items'].append({'id':task, 'state':state, 'source_event':payload['source_event'],
                'source_sha256':payload['source_sha256'], 'notification_id':payload['notification_id'],
                'capacity_at_event':payload['capacity_at_event'], 'payload_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                'grants_model_execution':False, 'desktop_chat_wakeup_connected':False})
        result['state'] = 'READ_ONLY_RESULT'
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        result.update(state='UNAVAILABLE', items=[])
    return result


def _identity(task, owner):
    if (not isinstance(task,str) or not re.fullmatch(r'capacity-followup:[1-9][0-9]{0,9}',task)
            or not isinstance(owner,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',owner)):
        raise ValueError('Capacity task and explicit host operator required')


def claim(root, task_id, fingerprint, owner):
    """Explicit host reservation only; never RPC/model-callable or leased replay."""
    _identity(task_id, owner)
    if not isinstance(fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',fingerprint):
        raise ValueError('Exact immutable payload SHA required')
    with closing(_connect(contained(root, 'agent_secretary.sqlite3'))) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT state,payload,scope_version FROM secretary_engineering_tasks WHERE id=?', (task_id,)).fetchone()
        if not row or row[0] != 'QUEUED_READ_ONLY': return {'state':'NOT_CLAIMED'}
        if row[2] != SCOPE or hashlib.sha256(row[1].encode()).hexdigest() != fingerprint:
            raise ValueError('Task scope/fingerprint conflict')
        with closing(_connect(contained(root,'runtime/recovery.sqlite3'),readonly=True)) as source:
            _, payload = _source(source, int(task_id.split(':')[1]))
        if _encode(payload) != row[1]: raise ValueError('Original source changed; reconciliation required')
        c.execute("UPDATE secretary_engineering_tasks SET state='STARTED_READ_ONLY',native=?,updated=? WHERE id=? AND state='QUEUED_READ_ONLY'",
                  (_encode({'owner':owner,'read_only':True}),time.time(),task_id))
        _status(c, task_id, 'STARTED_READ_ONLY')
    return {'state':'STARTED_READ_ONLY','task_id':task_id,'scope':SCOPE,'grants_model_execution':False,
            'automatic_deployment':False,'grants_cleanup_permission':False}


def _status(c, task, state, summary=''):
    c.execute('INSERT INTO secretary_events VALUES (?,?,?,?,?,?,?)',
        (task+':'+state, 'der-secretary','SYSTEM','ENGINEERING_STATUS',task,
         _encode({'state':state,'task_id':task,'summary':summary,'automatic_deployment':False}),time.time()))


def finish(root, task_id, owner, outcome, summary):
    _identity(task_id,owner)
    if outcome not in ('DIAGNOSED','UNKNOWN') or not isinstance(summary,str) or not 1 <= len(summary) <= 1000:
        raise ValueError('Bounded diagnostic outcome required')
    from .errors import redact
    with closing(_connect(contained(root,'agent_secretary.sqlite3'))) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT state,native,scope_version FROM secretary_engineering_tasks WHERE id=?',(task_id,)).fetchone()
        if not row or row[0] != 'STARTED_READ_ONLY' or row[2] != SCOPE or json.loads(row[1]).get('owner') != owner:
            raise PermissionError('Original read-only reservation required; no terminal replay')
        c.execute('UPDATE secretary_engineering_tasks SET state=?,updated=? WHERE id=?',(outcome,time.time(),task_id))
        _status(c,task_id,outcome,redact(summary))
    return {'state':outcome,'task_id':task_id,'automatic_deployment':False}
