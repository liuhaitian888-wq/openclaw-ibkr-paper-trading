"""Fail-closed production workspace and service ownership. Never kills a peer."""
import fcntl
import functools
import json
import os
from pathlib import Path
from contextlib import contextmanager
from trading.production_paths import CODE_ROOT, PRODUCTION_WORKSPACE, STATE_ROOT, RUNTIME_ROOT, AUDIT_DB, maintenance_active
from trading.production_diagnostics import context, ResourceMonitor


def validate_workspace(code_root=CODE_ROOT, expected=PRODUCTION_WORKSPACE, state_root=STATE_ROOT):
    code_root=Path(code_root).resolve();expected=Path(expected).resolve();state_root=Path(state_root).resolve()
    if code_root != expected or not (code_root/'.git').is_dir():
        raise RuntimeError('Production runner refused: linked worktrees are development-only; use '+str(expected))
    if state_root==code_root or code_root in state_root.parents or '/.codex/worktrees/' in str(state_root):
        raise RuntimeError('Production state must be outside repositories/worktrees')


@contextmanager
def instance_lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Production service already running: '+str(path))
        try:
            lock.seek(0);lock.truncate();json.dump({'pid':os.getpid(),**context()},lock);lock.flush()
            yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


@contextmanager
def production_service(service):
    validate_workspace()
    if os.getenv("AUDIT_DB") and Path(os.environ["AUDIT_DB"]).expanduser().resolve() != AUDIT_DB:
        raise RuntimeError("AUDIT_DB override conflicts with canonical production path")
    if maintenance_active(STATE_ROOT):raise RuntimeError('Production maintenance is active; startup refused')
    try:manifest=json.loads((STATE_ROOT/'production.json').read_text())
    except (OSError,ValueError):raise RuntimeError('Approved production manifest is missing')
    actual=context()
    if not actual['commit'] or not actual['branch']:
        raise RuntimeError('Git deployment identity is unavailable')
    if (manifest.get('ready') is not True or manifest.get('commit')!=actual['commit']
            or manifest.get('branch')!=actual['branch'] or manifest.get('workspace')!=str(CODE_ROOT)
            or manifest.get('state_root')!=str(STATE_ROOT)):
        raise RuntimeError('Production manifest/commit/path is not approved')
    from trading.production_diagnostics import command
    if command(['git','-C',str(CODE_ROOT),'status','--porcelain','--untracked-files=normal']).strip():
        raise RuntimeError('Production workspace has unapproved changes')
    require_module_gate('PRODUCTION_START_ALLOWED')
    with instance_lock(RUNTIME_ROOT/(service+'.lock')):
        with ResourceMonitor(service):yield


def guarded_service(service):
    def decorate(func):
        @functools.wraps(func)
        def run(*args,**kwargs):
            with production_service(service):return func(*args,**kwargs)
        return run
    return decorate


def module_gate(action, *, duplicate_or_unknown=True):
    """Read persistent evidence only. Missing evidence blocks, never opens a socket."""
    from contextlib import closing
    import sqlite3
    from reporting.health import resolve_modules, safety_gate
    observations={}
    try:
        path=RUNTIME_ROOT/'recovery.sqlite3'
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as c:
            observations={k:json.loads(v) for k,v in c.execute('SELECT name,payload FROM module_observations')}
        manifest=json.loads((STATE_ROOT/'production.json').read_text())
    except (OSError,ValueError,sqlite3.Error):manifest={}
    actual=context()
    approved = (manifest.get('ready') is True and bool(actual['commit']) and bool(actual['branch'])
        and manifest.get('commit')==actual['commit'] and manifest.get('branch')==actual['branch']
        and manifest.get('workspace')==str(CODE_ROOT) and manifest.get('state_root')==str(STATE_ROOT)
        and CODE_ROOT==PRODUCTION_WORKSPACE and (CODE_ROOT/'.git').is_dir()
        and manifest.get('environment')=='PAPER' and bool(manifest.get('account'))
        and manifest.get('migration_verified') is True)
    facts={**manifest.get('safety',{}),'manifest_approved':approved,
        'maintenance':maintenance_active(STATE_ROOT),
        'trading_paused':(STATE_ROOT/'PAUSED').exists(),
        'delivery_paused':(STATE_ROOT/'PAUSED').exists() or (STATE_ROOT/'DELIVERY_PAUSED').exists(),
        'duplicate_or_unknown':duplicate_or_unknown}
    if action=='ORDER_SUBMISSION_ALLOWED':
        account=observations.get('ACCOUNT',{})
        facts['identity_verified']=bool(facts.get('identity_verified') is True and manifest.get('account')
            and account.get('account')==manifest.get('account') and account.get('environment')==manifest.get('environment'))
    return safety_gate(action,resolve_modules(observations),facts)


def require_module_gate(action, *, duplicate_or_unknown=True):
    result=module_gate(action,duplicate_or_unknown=duplicate_or_unknown)
    if not result['allowed']:raise PermissionError('; '.join(result['reasons']))
    if action in ('ORDER_SUBMISSION_ALLOWED','FEISHU_SEND_ALLOWED'):
        from reporting.recovery import audit_write_probe
        from trading.production_paths import AUDIT_DB
        try:
            audit_write_probe(AUDIT_DB)
            import sqlite3
            from contextlib import closing
            journal=(RUNTIME_ROOT/'recovery.sqlite3').resolve()
            with closing(sqlite3.connect(journal.as_uri()+'?mode=rw',uri=True,timeout=.2)) as c,c:
                c.execute('INSERT INTO module_events(payload) VALUES (?)',(json.dumps({'persistence_check':action}),))
        except Exception as exc:
            try:
                from reporting.recovery import RecoveryCoordinator
                RecoveryCoordinator(RUNTIME_ROOT/'recovery.sqlite3').observe('DATABASE','FAILED',freshness='STALE',reason='Audit persistence failure; fresh reconciliation required')
            except Exception:pass  # This call still hard-blocks if diagnostic persistence also fails.
            raise PermissionError('Audit persistence unavailable; side effect forbidden') from exc


def guarded_broker_operation(func):
    """Protect every production broker submission, including protective orders."""
    import inspect
    @functools.wraps(func)
    def wrapped(*args,**kwargs):
        from reporting.recovery import RecoveryCoordinator
        bound=inspect.signature(func).bind(*args,**kwargs);bound.apply_defaults()
        proposal=bound.arguments.get('proposal')
        identity=bound.arguments.get('order_ref') or getattr(proposal,'idempotency_key',None)
        if not identity:raise PermissionError('Durable operation identity required')
        require_module_gate('ORDER_SUBMISSION_ALLOWED',duplicate_or_unknown=False)
        store=RecoveryCoordinator(RUNTIME_ROOT/'recovery.sqlite3')
        key='order:'+str(identity)
        if not store.begin_operation(key,'order',{'entrypoint':func.__name__}):raise PermissionError('Duplicate/uncertain broker operation')
        try:
            result=func(*args,**kwargs)
        except BaseException:
            store.finish_operation(key,'UNKNOWN')
            raise
        store.finish_operation(key,'UNKNOWN' if result.pending_confirmation else 'CONFIRMED')
        return result
    return wrapped


def require_connected_account(accounts):
    """Check the actual session, not a previous health observation, before submit."""
    try:manifest=json.loads((STATE_ROOT/'production.json').read_text())
    except (OSError,ValueError) as exc:
        raise PermissionError('Approved Paper account manifest is missing or invalid') from exc
    if (manifest.get('ready') is not True or manifest.get('environment')!='PAPER'
            or not str(manifest.get('account','')).startswith('DU')
            or list(accounts)!=[manifest['account']]):
        raise PermissionError('Connected broker account differs from approved production identity')
