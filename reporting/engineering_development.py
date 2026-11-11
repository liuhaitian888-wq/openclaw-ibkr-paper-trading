"""One pre-authorized engineering class; MODEL observations never become USER intent."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import time

from .agent_secretary import SecretaryArchive
from .database_console import contained
from .engineering_patch import CLASS, FILES, GUARD, command, prepare, apply, attest, test, digest
from .engineering_tasks import initialize, checkpoint
from .incidents import IncidentStore
from .native_journal import error_code
from .secretary_api import atomic
from .secretary_queue import CONVERSATION


def approved(value, now):
    scope = value.get('engineering_development_scope')
    if not isinstance(scope, dict):
        raise PermissionError('Development scope not configured')
    if (value.get('approved') is not True or value.get('model_owner') != 'cloud_oauth'
            or value.get('grants_trading_permission') is not False
            or scope.get('approved') is not True or scope.get('class') != CLASS
            or type(scope.get('max_tasks')) is not int or scope['max_tasks'] != 1
            or scope.get('grants_trading_permission') is not False
            or scope.get('grants_deployment_permission') is not False
            or not isinstance(scope.get('version'), str) or not 1 <= len(scope['version']) <= 100
            or not re.fullmatch('[a-f0-9]{40}', str(scope.get('base_commit', '')))
            or any(type(scope.get(k)) not in (int, float) for k in ('since', 'expires'))
            or not 0 < scope['since'] <= now < scope['expires'] <= scope['since']+86400
            or type(value.get('model_owner_since')) not in (int, float)
            or scope['since'] < value['model_owner_since']
            or scope.get('authority') != {'kind': 'CODEX_HUMAN_AUTHORIZATION',
                'thread_id': '01a1c855-b112-7351-a5b1-0f9173f49ea5',
                'message_id': '01a1c85c-9911-7cf0-a5f2-8c8840382068'}):
        raise PermissionError('Exact expiring owner-authorized engineering class required')
    return scope


def source_root():
    return Path(__file__).resolve().parents[1]


def check_source(scope):
    root = source_root()
    result = command(['/usr/bin/git', 'rev-parse', 'HEAD'], cwd=root, home=Path('/nonexistent'))
    if result['exit_code'] or result['stdout'].strip() != scope['base_commit']:
        raise PermissionError('Development base must match current approved source')
    dirty = command(['/usr/bin/git', '-c', 'core.fsmonitor=false', 'status', '--porcelain', '--untracked-files=no', '--', *FILES],
                    cwd=root, home=Path('/nonexistent'))
    if dirty['exit_code'] or dirty['stdout'].strip():
        raise PermissionError('Authorized source files differ from the approved commit')
    return root


def tool(archive, root, request, value, *, instruction, run):
    scope = approved(value, archive.clock()); source = check_source(scope)
    with closing(archive.connect()) as c:
        current = c.execute('SELECT instruction,state,started_at FROM secretary_runs WHERE occurrence=?', (run,)).fetchone()
    if current is None or current[:2] != (instruction, 'STARTED') or current[2] < scope['since']:
        raise PermissionError('Fresh current secretary run required')
    if request['name'] == 'engineering_development_context':
        code = (source/FILES[0]).read_text()
        return {'class': CLASS, 'base_commit': scope['base_commit'], 'authorized_files': list(FILES),
            'candidate': 'Malformed policy values must yield PermissionError; timestamp comparison currently precedes type checks.',
            'source_excerpt': code[code.index('def policy('):code.index('\ndef native_instruction(')],
            'source_sha256': digest(source/FILES[0]), 'authority': scope['authority'],
            'submit_schema': {'name': 'engineering_development_submit', 'proposal': {
                'title': '简短问题名', 'observation': '实际源码问题', 'suggested_change': '限定修复',
                'evidence': ['source SHA或实际观察记录']}},
            'limits': 'MODEL may propose; only this pre-authorized class generates an isolated patch/tests. No deploy/trade.'}
    if request['name'] != 'engineering_development_submit':
        raise PermissionError('Registered development tool required')
    if set(request)-{'name', 'source', 'proposal_id', 'proposal'} or ('proposal_id' in request and 'proposal' in request):
        raise PermissionError('Only proposal evidence may be submitted; no commands or paths')
    proposal = request.get('proposal_id')
    if 'proposal' in request:
        from .engineering_relay import propose
        proposal = propose(archive, request['proposal'], instruction=instruction)['id']
    if not isinstance(proposal, str) or not re.fullmatch('engineering-proposal:[a-f0-9]{24}', proposal):
        raise ValueError('Existing MODEL proposal identity required')
    with closing(archive.connect()) as c:
        original = c.execute("SELECT payload FROM secretary_events WHERE occurrence=? AND origin='MODEL' AND kind='ENGINEERING_PROPOSAL'", (proposal,)).fetchone()
    if original is None:
        raise PermissionError('MODEL proposal provenance required')
    initialize(archive)
    authority = 'engineering-authorization:'+scope['version']
    archive.append(authority, CONVERSATION, origin='USER', kind='STANDING_AUTHORIZATION',
        payload={'source_kind': 'CODEX_HUMAN_AUTHORIZATION', 'source': scope['authority'],
            'approved_scope': scope, 'not_a_native_telegram_message': True})
    identity = 'engineering-development:'+hashlib.sha256((scope['version']+':'+proposal).encode()).hexdigest()
    task_instruction = identity+':instruction'
    archive.append(task_instruction, CONVERSATION, origin='SYSTEM', kind='ENGINEERING_INSTRUCTION', parent=authority,
        payload={'authorized_class': CLASS, 'authority': authority, 'proposal_id': proposal,
            'proposal_origin': 'MODEL', 'model_proposal': json.loads(original[0])})
    payload = json.dumps({'scope': CLASS, 'scope_policy': scope, 'authority': authority,
        'proposal_id': proposal, 'model_proposal': json.loads(original[0]), 'requested_by_run': run}, ensure_ascii=False, sort_keys=True)
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT id,state FROM secretary_engineering_tasks WHERE scope_version=?', (scope['version'],)).fetchone()
        if existing:
            return {'state': existing[1], 'task_id': existing[0], 'replayed': False}
        c.execute("INSERT INTO secretary_engineering_tasks VALUES (?,?,?,'QUEUED',?,'{}',?,?)",
                  (identity, task_instruction, scope['version'], payload, archive.clock(), archive.clock()))
    archive.append(identity+':queued', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS', parent=proposal,
        payload={'state': 'QUEUED_NOT_NATIVE_ACCEPTED', 'task_id': identity, 'authority': authority,
                 'class': CLASS, 'automatic_deployment': False})
    return {'state': 'QUEUED_NOT_NATIVE_ACCEPTED', 'task_id': identity, 'authority': authority,
            'proposal_origin': 'MODEL', 'automatic_deployment': False}


def reserve(archive, value):
    scope = approved(value, archive.clock()); check_source(scope)
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT id,instruction,payload FROM secretary_engineering_tasks WHERE scope_version=? AND state='QUEUED'", (scope['version'],)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[2])
        if payload['scope_policy'] != scope or payload.get('scope') != CLASS:
            raise PermissionError('Queued scope identity changed')
        authority = c.execute("SELECT origin,kind,payload FROM secretary_events WHERE occurrence=?", (payload['authority'],)).fetchone()
        if authority is None or authority[:2] != ('USER', 'STANDING_AUTHORIZATION') or json.loads(authority[2])['approved_scope'] != scope:
            raise PermissionError('Owner standing authority lost')
        if c.execute("SELECT 1 FROM secretary_runs WHERE model='gpt-6.1-sol' AND state='STARTED' AND started_at>=? LIMIT 1", (value['model_owner_since'],)).fetchone():
            return None
        if c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol' AND started_at>=?", (int(archive.clock()//86400)*86400,)).fetchone()[0] >= 24:
            return None
        if c.execute("UPDATE secretary_engineering_tasks SET state='STARTED',updated=? WHERE id=? AND state='QUEUED'", (archive.clock(), row[0])).rowcount != 1:
            return None
        c.execute("INSERT INTO secretary_runs VALUES (?,?,'gpt-6.1-sol','STARTED',NULL,?)", (row[0], row[1], archive.clock()))
    return {'id': row[0], 'instruction': row[1], 'payload': payload}



def notice(archive, store, identity, stage, text, *, config=None):
    """Bind replies to the host-verified native request, never MODEL labels."""
    if stage not in ('ACCEPTED', 'RESULT', 'UNKNOWN'):
        raise ValueError('Fixed development notice stage required')
    config = config if isinstance(config, dict) else {}
    native = False
    instruction = None
    with closing(archive.connect()) as c:
        row = c.execute('SELECT payload,created FROM secretary_engineering_tasks WHERE id=?', (identity,)).fetchone()
        task = json.loads(row[0]) if row else {}
        scope = task.get('scope_policy', {})
        request_run = task.get('requested_by_run')
        source = c.execute("""SELECT r.instruction,r.started_at,e.origin,e.kind,e.payload,e.recorded_at,s.received_at
            FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.instruction
            JOIN secretary_received s ON s.instruction=e.occurrence WHERE r.occurrence=?""", (request_run,)).fetchone() if isinstance(request_run, str) else None
    if (source and task.get('scope') == CLASS and isinstance(scope, dict)
            and all(type(scope.get(k)) in (int, float) for k in ('since', 'expires'))
            and source[2] == 'USER' and source[3] in ('CHAT_INSTRUCTION', 'CONTROL_INSTRUCTION')):
        data = json.loads(source[4]); owner = data.get('chat_id')
        native = bool(type(owner) is int and owner > 0
            and config.get('owner_user_id') == owner
            and config.get('owner_private_chat_id') == owner
            and config.get('owner_private_verified') is True
            and data.get('source') == 'Telegram native owner message'
            and data.get('native_authority') == {'sender_id': owner, 'chat_type': 'private',
                'is_bot': False, 'forwarded': False, 'edited': False}
            and type(data.get('update_id')) is int and data['update_id'] >= 0
            and type(data.get('message_id')) is int and data['message_id'] > 0
            and source[0] == 'telegram:'+str(owner)+':'+str(data['update_id'])
            and type(data.get('timestamp')) is int
            and all(scope['since'] <= at < scope['expires'] and at <= row[1] for at in
                (data['timestamp'], source[1], source[5], source[6])))
        if native:
            instruction = source[0]
    payload = json.dumps({'reason': text, 'delivery_transport': 'telegram', 'message_role': 'CONTROL',
        'requires_response': True, 'sensitivity': 'PRIVATE_ACCOUNT_OPERATIONS',
        'native_owner_reply': native, 'instruction': instruction, 'engineering_task': identity}, ensure_ascii=False)
    with closing(store.connect()) as c, c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",
                  ('secretary-engineering:' + identity + ':' + stage, payload))


def finish(archive, store, job, report, *, config=None):
    outcome = report['outcome']; ready = outcome == 'PATCH_READY'
    text = ('授权参数校验修复｜'+('补丁和隔离测试已完成，等待审阅。' if ready else '校验未完成，已保留记录等待核对。')
        +'\n编号：T'+job['id'][-8:].upper()
        +'\n尚未部署，生产业务数据和交易权限未变更。')
    result = job['id']+':result'
    archive.append(result, CONVERSATION, origin='TOOL', kind='ENGINEERING_DEVELOPMENT_RESULT', parent=job['instruction'],
        payload={'message': text, 'report': report})
    archive.finish_run(job['id'], state='SUCCEEDED' if ready else 'FAILED', result_event=result)
    with closing(archive.connect()) as c, c:
        c.execute('UPDATE secretary_engineering_tasks SET state=?,updated=? WHERE id=?', (outcome, archive.clock(), job['id']))
    notice(archive, store, job['id'], 'RESULT', text, config=config)
    archive.append(job['id']+':status', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS',
        parent=job['payload']['proposal_id'], payload={'state': outcome, 'task_id': job['id'],
            'artifact_dir': report['artifact_dir'], 'automatic_deployment': False})


def run_once(root, value, *, home, backend=None, tester=None, config=None):
    """Existing kernel model owner calls this serially, never a new service."""
    if 'engineering_development_scope' not in value:
        return 'DISABLED'
    archive = SecretaryArchive(root/'agent_secretary.sqlite3'); store = IncidentStore(root/'runtime/recovery.sqlite3')
    initialize(archive)
    with closing(archive.connect()) as c:
        results = c.execute("SELECT occurrence,payload FROM secretary_events WHERE kind='ENGINEERING_DEVELOPMENT_RESULT' ORDER BY rowid DESC LIMIT 20").fetchall()
        prior = c.execute("SELECT id,instruction,payload FROM secretary_engineering_tasks WHERE state='STARTED' AND json_extract(payload,'$.scope')=? LIMIT 1", (CLASS,)).fetchone()
    for identity, payload in results:
        notice(archive, store, identity.removesuffix(':result'), 'RESULT', json.loads(payload)['message'], config=config)
    if prior:
        job = {'id': prior[0], 'instruction': prior[1], 'payload': json.loads(prior[2])}
        artifact = contained(root, 'engineering/development/'+prior[0].split(':')[1]+'/result.json')
        if artifact.is_file():
            report = json.loads(artifact.read_text())
            if report.get('task_id') != prior[0]:
                raise PermissionError('Artifact task identity mismatch')
            finish(archive, store, job, report, config=config)
            return 'COMPLETION_RECONCILED'
        return 'STARTED_REQUIRES_RECONCILIATION'
    try:
        approved(value, archive.clock()); check_source(value['engineering_development_scope'])
    except PermissionError:
        return 'SCOPE_INACTIVE'
    from .storage_policy import engineering_preflight
    budget = engineering_preflight(root)
    if not budget['allowed']:
        return budget['state']  # Before reserve, canary, source copy or model call.
    from .engineering_sandbox import capabilities
    try:
        capabilities()  # No untrusted code starts on unsupported kernels.
    except (OSError, PermissionError):
        return 'SANDBOX_UNAVAILABLE'
    job = reserve(archive, value)
    if job is None:
        return 'IDLE'
    folder = 'engineering/development/'+job['id'].split(':')[1]
    location = contained(root, folder)
    deadline = time.monotonic()+130
    def remaining(cap):
        left = min(cap, deadline-time.monotonic())
        if left < 1:
            raise TimeoutError('Whole development task deadline')
        return left
    try:
        source = prepare(source_root(), job['payload']['scope_policy']['base_commit'], location, deadline=deadline, storage_root=root)
        def phase(name):
            archive.append(job['id']+':phase:'+name, CONVERSATION, origin='SYSTEM',
                kind='ENGINEERING_TEST_STAGE', parent=job['instruction'],
                payload={'phase': name, 'class': CLASS, 'base_commit': source['upstream_commit']})
        def runner(location, profile):
            phase(profile.upper()+'_STARTED' if profile != 'regression' or not (location/'patch.diff').exists() else 'PATCH_REGRESSION_STARTED')
            return (tester or test)(location, profile, timeout=remaining(15))
        canary = runner(location, 'canary')
        atomic(location/'canary.json', canary)
        if canary['exit_code'] != 0 or json.loads(canary['stdout']).get('passed') is not True:
            raise PermissionError('Real kernel canary failed; no untrusted execution')
        baseline = runner(location, 'regression'); atomic(location/'baseline.json', baseline)
        evidence = json.loads(baseline['stdout'])
        if baseline['exit_code'] == 0:
            report = {'outcome': 'BASELINE_DEFECT_NOT_REPRODUCED'}
        elif (evidence.get('regression') != CLASS or evidence.get('cases') != 7
                or not evidence.get('failures') or any(x not in ('TypeError', 'AttributeError') for x in evidence['failures'])):
            report = {'outcome': 'BASELINE_UNAVAILABLE'}
        else:
            from .codex_appserver import run
            context = {'class': CLASS, 'authorization': job['payload']['scope_policy']['authority'],
                'proposal_origin': 'MODEL', 'proposal': job['payload']['model_proposal'],
                'source': source, 'baseline': baseline, 'required_guard': GUARD,
                'edit_contract': 'Edit only reporting/engineering_tasks.py. Insert exactly the supplied guards after scope assignment; preserve all other AST. Tests are read-only and supplied independently by the host.'}
            def record(stage, receipt):
                checkpoint(archive, job, stage, receipt)
                if stage == 'TURN_ACCEPTED':
                    archive.append(job['id']+':accepted', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS',
                        parent=job['payload']['proposal_id'], payload={'state': 'NATIVE_ACCEPTED', 'task_id': job['id'],
                            'thread_id': receipt['thread_id'], 'turn_id': receipt['turn_id'], 'automatic_deployment': False})
                    notice(archive, store, job['id'], 'ACCEPTED', 'Hetzner Codex已原生接下受限补丁任务，隔离测试结果与工件将回到本私聊。', config=config)
            native = (backend or run)(context, home=home, empty_dir=contained(root, 'secretary-oauth-empty'),
                purpose='scoped_patch', timeout=remaining(75), record=record,
                journal_path=location/'native-journal.json')
            atomic(location/'native-result.json', native)
            patch = apply(location, native)
            validation = runner(location, 'regression'); atomic(location/'regression.json', validation)
            suite = runner(location, 'tests'); atomic(location/'tests.json', suite)
            attestation = attest(location, patch)
            report = {'outcome': 'PATCH_READY' if validation['exit_code'] == 0 and suite['exit_code'] == 0 else 'VALIDATION_FAILED',
                'patch': patch, 'attestation': attestation, 'native': {k: v for k, v in native.items() if k != 'edits'},
                'regression_exit': validation['exit_code'], 'tests_exit': suite['exit_code'],
                'validation_scope': 'Fixed regression plus engineering-task suite; publisher full suite/review still required.'}
        report.update(task_id=job['id'], artifact_dir=folder, base_commit=source['upstream_commit'],
                      scope=CLASS, authority=job['payload']['authority'], proposal_origin='MODEL')
        atomic(location/'result.json', report)
        finish(archive, store, job, report, config=config)
        return report['outcome']
    except BaseException as exc:
        if (location/'result.json').is_file():
            # Public result already committed: only repair projection next time.
            return 'COMPLETION_RECONCILIATION_REQUIRED'
        archive.append(job['id']+':uncertainty', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS',
            parent=job['instruction'], payload={'state': 'UNKNOWN', 'error_type': type(exc).__name__, 'error_code': error_code(exc), 'automatic_replay': False})
        with closing(archive.connect()) as c, c:
            c.execute("UPDATE secretary_engineering_tasks SET state='UNKNOWN',updated=? WHERE id=?", (archive.clock(), job['id']))
        archive.finish_run(job['id'], state='UNKNOWN')
        notice(archive, store, job['id'], 'UNKNOWN', '受限开发结果待核对；保留补丁/检查点，不会自动重做。', config=config)
        archive.append(job['id']+':status', CONVERSATION, origin='SYSTEM', kind='ENGINEERING_STATUS',
            parent=job['payload']['proposal_id'], payload={'state': 'UNKNOWN', 'task_id': job['id'], 'automatic_replay': False})
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return 'UNKNOWN'
