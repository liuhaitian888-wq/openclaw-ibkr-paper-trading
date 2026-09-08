"""Fail-closed production workspace and service ownership. Never kills a peer."""
import fcntl
import functools
import json
import os
from pathlib import Path
from contextlib import contextmanager
from trading.production_paths import CODE_ROOT, PRODUCTION_WORKSPACE, STATE_ROOT, RUNTIME_ROOT, AUDIT_DB
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
    if (STATE_ROOT/'MAINTENANCE').exists():raise RuntimeError('Production maintenance is active; startup refused')
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
    with instance_lock(RUNTIME_ROOT/(service+'.lock')):
        with ResourceMonitor(service):yield


def guarded_service(service):
    def decorate(func):
        @functools.wraps(func)
        def run(*args,**kwargs):
            with production_service(service):return func(*args,**kwargs)
        return run
    return decorate
