"""One-shot registered DB diagnostics through the existing cloud OAuth owner.

No model RPC exposes this module. Native tools and arbitrary owner-text execution
are unavailable. Hosted Cloud tasks and their UNKNOWN outcomes are separate.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .database_console import DATABASES, contained, inspect_database
from .errors import redact
from .secretary_queue import CONVERSATION, enqueue_reply
from .secretary_read import query
from .secretary_api import atomic

SCOPE = 'registered-db-diagnostic-v1'
COMMANDS = frozenset(('/codex dbcheck', '/codex 只读数据库检查'))
EXECUTOR = 'hetzner_codex_appserver'


def initialize(archive):
    with closing(archive.connect()) as c, c:
        c.execute('''CREATE TABLE IF NOT EXISTS secretary_engineering_tasks(
            id TEXT PRIMARY KEY, instruction TEXT NOT NULL UNIQUE,
            scope_version TEXT NOT NULL, state TEXT NOT NULL,
            payload TEXT NOT NULL, native TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL, updated REAL NOT NULL)''')


def policy(value, *, now):
    """A separate expiring one-attempt scope; a model cannot construct authority."""
    scope = value.get('engineering_scope', {})
    if (value.get('approved') is not True or value.get('model_owner') != 'cloud_oauth'
            or value.get('grants_trading_permission') is not False
            or scope.get('executor') != EXECUTOR or scope.get('scope') != SCOPE
            or scope.get('approved') is not True or type(scope.get('max_tasks')) is not int or scope.get('max_tasks') != 1
            or scope.get('grants_trading_permission') is not False
            or scope.get('grants_deployment_permission') is not False
            or type(value.get('model_owner_since')) not in (int, float)
            or not 0 < value['model_owner_since'] <= scope.get('since', 0)
            or not isinstance(scope.get('version'), str) or not 1 <= len(scope['version']) <= 100
            or type(scope.get('since')) not in (int, float)
            or type(scope.get('expires')) not in (int, float)
            or not 0 < scope['since'] <= now < scope['expires'] <= scope['since'] + 86400):
        raise PermissionError('Approved fresh one-shot engineering scope required')
    return scope


def native_instruction(archive, instruction, config, scope):
    with closing(archive.connect()) as c:
        row = c.execute('SELECT origin,kind,payload,recorded_at FROM secretary_events WHERE occurrence=?',
                        (instruction,)).fetchone()
        received = c.execute('SELECT received_at FROM secretary_received WHERE instruction=?', (instruction,)).fetchone()
    if row is None or row[:2] != ('USER', 'CONTROL_INSTRUCTION') or received is None:
        raise PermissionError('Verified native private owner instruction required')
    data = json.loads(row[2]); auth = data.get('native_authority', {})
    owner = config.get('owner_user_id')
    if (type(owner) is not int or config.get('owner_private_verified') is not True
            or config.get('owner_private_chat_id') != owner
            or data.get('source') != 'Telegram native owner message'
            or data.get('chat_id') != owner or auth != {'sender_id': owner,
                'chat_type': 'private', 'is_bot': False, 'forwarded': False, 'edited': False}
            or type(data.get('update_id')) is not int or data['update_id'] < 0
            or type(data.get('message_id')) is not int or data['message_id'] < 1
            or instruction != 'telegram:' + str(owner) + ':' + str(data['update_id'])
            or data.get('text', '').strip() not in COMMANDS
            or type(data.get('timestamp')) is not int
            or not scope['since'] <= data['timestamp'] < scope['expires']
            or not scope['since'] <= row[3] < scope['expires']
            or not scope['since'] <= received[0] < scope['expires']):
        raise PermissionError('Fresh exact native dbcheck scope required')
    return data


def enqueue(archive, config, value):
    initialize(archive)
    scope = policy(value, now=archive.clock())
    with closing(archive.connect()) as c:
        rows = c.execute("""SELECT occurrence FROM secretary_events WHERE origin='USER'
            AND kind='CONTROL_INSTRUCTION' AND recorded_at>=? AND recorded_at<?
            AND trim(json_extract(payload,'$.text')) IN (?,?)
            ORDER BY rowid LIMIT 20""", (scope['since'], scope['expires'], *sorted(COMMANDS))).fetchall()
    for (instruction,) in rows:
        try:
            data = native_instruction(archive, instruction, config, scope)
        except PermissionError:
            continue
        identity = 'engineering:' + hashlib.sha256(instruction.encode()).hexdigest()
        payload = json.dumps({'scope': SCOPE, 'executor': EXECUTOR, 'owner_instruction': data,
            'scope_policy': scope}, ensure_ascii=False, sort_keys=True)
        with closing(archive.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT payload FROM secretary_engineering_tasks WHERE id=?', (identity,)).fetchone()
            if existing:
                if existing[0] != payload:
                    raise ValueError('Engineering occurrence content conflict')
                continue
            # One accepted scope identity includes QUEUED, STARTED and UNKNOWN.
            if c.execute('SELECT 1 FROM secretary_engineering_tasks WHERE scope_version=?', (scope['version'],)).fetchone():
                continue
            c.execute("INSERT INTO secretary_engineering_tasks VALUES (?,?,?,'QUEUED',?,'{}',?,?)",
                      (identity, instruction, scope['version'], payload, archive.clock(), archive.clock()))


def claim(archive, config, value):
    scope = policy(value, now=archive.clock())
    with closing(archive.connect()) as c:
        row = c.execute("SELECT id,instruction,payload FROM secretary_engineering_tasks WHERE state='QUEUED' AND scope_version=? ORDER BY created LIMIT 1", (scope['version'],)).fetchone()
    if row is None:
        return None
    native_instruction(archive, row[1], config, scope)
    if json.loads(row[2])['scope_policy'] != scope:
        raise PermissionError('Queued task scope changed; explicit reconciliation required')
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM secretary_runs WHERE model='gpt-6.1-sol' AND state='STARTED' AND started_at>=? AND NOT EXISTS(SELECT 1 FROM secretary_events e WHERE e.occurrence=secretary_runs.occurrence||':reconciliation' AND e.kind='RUN_RECONCILIATION' AND e.origin='SYSTEM') LIMIT 1", (value['model_owner_since'],)).fetchone():
            return None
        if c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol' AND started_at>=?", (int(archive.clock() // 86400)*86400,)).fetchone()[0] >= 24:
            return None
        if c.execute("UPDATE secretary_engineering_tasks SET state='STARTED',updated=? WHERE id=? AND state='QUEUED'", (archive.clock(), row[0])).rowcount != 1:
            return None
        c.execute("INSERT INTO secretary_runs VALUES (?,?,'gpt-6.1-sol','STARTED',NULL,?)", (row[0], row[1], archive.clock()))
    return {'id': row[0], 'instruction': row[1], 'payload': json.loads(row[2])}


def control_receipt(archive, config, value, instruction):
    """Truthful deterministic /codex receipt; no model execution in the inbox."""
    try:
        scope = policy(value, now=archive.clock())
        native_instruction(archive, instruction, config, scope)
    except PermissionError:
        return None
    enqueue(archive, config, value)
    with closing(archive.connect()) as c:
        row = c.execute('SELECT state,native FROM secretary_engineering_tasks WHERE instruction=?', (instruction,)).fetchone()
    if row is None:
        return '本次只读数据库检查范围已登记其他任务，不能再提交；现有任务和未知结果保留。'
    state, native = row[0], json.loads(row[1])
    descriptions = {'QUEUED': '已排队，等待原生接单。',
        'STARTED': '已保留执行身份，等待原生确认。', 'SUCCEEDED': '已完成，结果另行回到本私聊。',
        'UNKNOWN': '结果待核对，不会自动重做。'}
    if state == 'STARTED' and native.get('turn_id'):
        descriptions['STARTED'] = '已原生接单，结果将回到本私聊。'
    return 'Hetzner Codex执行器｜只读数据库检查\n' + descriptions[state]


def diagnostic(root, *, now):
    """Fixed queries only: no SQL, paths or commands from user/model input."""
    databases = []
    for definition in DATABASES:
        metadata = inspect_database(root, definition, now=now)
        database = definition[0]
        try:
            tables = query(root, database, "SELECT count(*) AS table_count FROM sqlite_master WHERE type='table'")
            schema = query(root, database, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        except (OSError, ValueError, sqlite3.Error) as exc:
            tables = schema = {'state': 'UNAVAILABLE_OR_BUDGET', 'error_type': type(exc).__name__}
        latest = metadata.get('last_business_at')
        if latest:
            from datetime import datetime
            age = now - datetime.fromisoformat(latest).timestamp()
            freshness = 'RECENT_PROBE' if 0 <= age <= 300 else 'STALE_PROBE'
        else:
            freshness = 'UNKNOWN'
        databases.append({'database': database, 'metadata': metadata,
            'table_count_evidence': tables, 'table_names_evidence': schema,
            'probe_freshness': freshness})
    return {'scope': SCOPE, 'observed_at': now, 'databases': databases,
        'limitations': ['Each query is bounded and read-only; no cross-database atomicity.',
            'Probe times do not establish whole-database freshness or broker connectivity.',
            'No production integrity scan, checkpoint, broker requests or configuration changes.']}


def checkpoint(archive, job, stage, native):
    if stage not in ('THREAD_CREATED', 'TURN_ACCEPTED', 'TURN_COMPLETED'):
        raise ValueError('Registered native checkpoint required')
    archive.append(job['id'] + ':' + stage, CONVERSATION, origin='SYSTEM', kind='ENGINEERING_NATIVE_RECEIPT',
        parent=job['instruction'], payload={'executor': EXECUTOR, 'stage': stage, **redact(native)})
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT native FROM secretary_engineering_tasks WHERE id=? AND state=\'STARTED\'', (job['id'],)).fetchone()
        if row is None:
            raise ValueError('Reserved task required')
        prior = json.loads(row[0])
        if any(prior.get(k, v) != v for k, v in native.items() if k in ('thread_id', 'turn_id')):
            raise ValueError('Native identity cannot change')
        c.execute('UPDATE secretary_engineering_tasks SET native=?,updated=? WHERE id=?',
                  (json.dumps({**prior, **redact(native), 'stage': stage}, ensure_ascii=False), archive.clock(), job['id']))


def notice(store, identity, stage, text):
    """Only enqueue; the existing sender alone resolves exact private identity."""
    payload = json.dumps({'reason': text, 'delivery_transport': 'telegram', 'message_role': 'CONTROL',
        'requires_response': True, 'sensitivity': 'PRIVATE_ACCOUNT_OPERATIONS'}, ensure_ascii=False)
    with closing(store.connect()) as c, c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",
                  ('secretary-engineering:' + identity + ':' + stage, payload))


def finish(archive, store, root, job, native, evidence):
    """Public output and deterministic evidence persist before success/outbox projections."""
    if native.get('status') != 'completed' or not all(native.get(k) for k in ('thread_id', 'turn_id', 'summary')):
        raise ValueError('Native completed turn/public output required')
    name = job['id'].split(':')[1]
    report = {'task_id': job['id'], 'executor': EXECUTOR, 'scope': SCOPE,
        'native': native, 'evidence': evidence, 'grants_trading_permission': False,
        'grants_deployment_permission': False}
    path = contained(root, 'engineering/codex-executor/' + name + '/report.json')
    if path.exists():
        if json.loads(path.read_text()) != report:
            raise ValueError('Immutable engineering report conflict')
    else:
        atomic(path, report)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = []
    for db in evidence['databases']:
        counts = db['table_count_evidence'].get('rows', [])
        count = counts[0]['table_count'] if counts else '未知'
        rows.append(db['database'] + '：' + str(count) + '张表；' + db['probe_freshness']
            + '；源时间 ' + str(db['metadata'].get('last_business_at') or '未知'))
    summary = ('Hetzner Codex执行器｜只读数据库检查已完成\n' + '\n'.join(rows)
        + '\n' + native['summary'][:1000] + '\n报告：' + str(path.relative_to(root))
        + '\nSHA256：' + digest + '\n编号：T' + hashlib.sha256(job['instruction'].encode()).hexdigest()[:8].upper())
    result = job['id'] + ':result'
    archive.append(result, CONVERSATION, origin='TOOL', kind='ENGINEERING_RESULT', parent=job['instruction'],
        payload={'summary': redact(summary), 'response_mode': 'CONTROL', 'report_sha256': digest,
                 'report': str(path.relative_to(root)), 'native': native, 'executor': EXECUTOR})
    archive.append(job['id'] + ':presentation', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_PRESENTATION',
        parent=job['instruction'], payload={'requires_response': True, 'sensitivity': 'PRIVATE_ACCOUNT_OPERATIONS'})
    archive.finish_run(job['id'], state='SUCCEEDED', result_event=result)
    with closing(archive.connect()) as c, c:
        c.execute("UPDATE secretary_engineering_tasks SET state='SUCCEEDED',updated=? WHERE id=?", (archive.clock(), job['id']))
    enqueue_reply(archive, store, job['id'], redact(summary), role='CONTROL')


def run_once(root, config, value, *, home, backend=None):
    """Called only inside the held secretary-cloud-model kernel lock, serially."""
    from .agent_secretary import SecretaryArchive
    from .incidents import IncidentStore
    from .codex_appserver import run, preflight
    if 'engineering_scope' not in value:
        return 'DISABLED'
    archive = SecretaryArchive(root / 'agent_secretary.sqlite3')
    store = IncidentStore(root / 'runtime/recovery.sqlite3')
    initialize(archive)
    # Idempotent enqueue repairs an archive/outbox interruption without HTTP replay.
    with closing(archive.connect()) as c:
        completed = c.execute("SELECT t.id,e.payload FROM secretary_engineering_tasks t JOIN secretary_runs r ON r.occurrence=t.id JOIN secretary_events e ON e.occurrence=r.result_event WHERE r.state='SUCCEEDED' AND json_extract(t.payload,'$.scope')=? ORDER BY t.created DESC LIMIT 20", (SCOPE,)).fetchall()
    for identity, payload in completed:
        enqueue_reply(archive, store, identity, json.loads(payload)['summary'], role='CONTROL')
    # Completion after a crash is repaired from a native completed checkpoint,
    # never by issuing a new thread/turn. No STARTED/UNKNOWN model retry exists.
    with closing(archive.connect()) as c:
        prior = c.execute("SELECT id,instruction,payload,native FROM secretary_engineering_tasks WHERE state='STARTED' AND json_extract(payload,'$.scope')=? ORDER BY created LIMIT 1", (SCOPE,)).fetchone()
    if prior:
        native = json.loads(prior[3])
        if native.get('stage') != 'TURN_COMPLETED':
            with closing(archive.connect()) as c:
                completed = c.execute("SELECT payload FROM secretary_events WHERE occurrence=? AND origin='SYSTEM' AND kind='ENGINEERING_NATIVE_RECEIPT'", (prior[0] + ':TURN_COMPLETED',)).fetchone()
            if completed:
                payload = json.loads(completed[0])
                native = {k: v for k, v in payload.items() if k not in ('stage', 'executor')}
                checkpoint(archive, {'id': prior[0], 'instruction': prior[1]}, 'TURN_COMPLETED', native)
                native['stage'] = 'TURN_COMPLETED'
        evidence_path = contained(root, 'engineering/codex-executor/' + prior[0].split(':')[1] + '/evidence.json')
        if native.get('stage') == 'TURN_COMPLETED' and evidence_path.is_file():
            finish(archive, store, root, {'id': prior[0], 'instruction': prior[1]},
                   {k: v for k, v in native.items() if k != 'stage'}, json.loads(evidence_path.read_text()))
            return 'COMPLETION_RECONCILED'
        return 'STARTED_REQUIRES_RECONCILIATION'
    try:
        policy(value, now=archive.clock())
    except PermissionError:
        return 'SCOPE_INACTIVE'
    preflight(home)
    enqueue(archive, config, value)
    job = claim(archive, config, value)
    if job is None:
        return 'IDLE'
    try:
        evidence = diagnostic(root, now=archive.clock())
        folder = 'engineering/codex-executor/' + job['id'].split(':')[1]
        atomic(contained(root, folder + '/evidence.json'), evidence)
        empty = contained(root, 'secretary-oauth-empty')
        def record(stage, result):
            checkpoint(archive, job, stage, result)
            if stage == 'TURN_ACCEPTED':
                notice(store, job['id'], 'ACCEPTED', 'Hetzner Codex执行器已原生接下只读数据库检查；完成结果将回到此私聊。')
        native = (backend or run)(evidence, home=home, empty_dir=empty, record=record)
        finish(archive, store, root, job, native, evidence)
        return 'SUCCEEDED'
    except BaseException as exc:
        # A persisted completion remains repairable even if artifact/outbox failed.
        with closing(archive.connect()) as c, c:
            current = json.loads(c.execute('SELECT native FROM secretary_engineering_tasks WHERE id=?', (job['id'],)).fetchone()[0])
            if current.get('stage') != 'TURN_COMPLETED':
                c.execute("UPDATE secretary_engineering_tasks SET state='UNKNOWN',updated=? WHERE id=?", (archive.clock(), job['id']))
        if current.get('stage') != 'TURN_COMPLETED':
            archive.finish_run(job['id'], state='UNKNOWN')
        notice(store, job['id'], 'UNKNOWN', 'Hetzner Codex执行器的结果待核对；原任务和原生检查点已保留，不会自动重做。')
        archive.append(job['id'] + ':uncertainty', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS',
            parent=job['instruction'], payload={'state': 'UNKNOWN', 'error_type': type(exc).__name__,
                'executor': EXECUTOR, 'automatic_replay': False})
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return 'UNKNOWN'
