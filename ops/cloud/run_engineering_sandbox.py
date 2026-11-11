"""Finite fixed-profile test child. No model credentials or production state access."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.engineering_sandbox import enforce


def regression():
    from reporting.engineering_tasks import policy
    base = {'approved': True, 'model_owner': 'cloud_oauth', 'model_owner_since': 1,
        'grants_trading_permission': False, 'engineering_scope': {'approved': True,
        'executor': 'hetzner_codex_appserver', 'scope': 'registered-db-diagnostic-v1',
        'version': 'test', 'since': 2, 'expires': 20, 'max_tasks': 1,
        'grants_trading_permission': False, 'grants_deployment_permission': False}}
    failures = []
    import copy
    for malformed in (None, [], 'invalid', {'since': 'invalid'}, {'since': None}, {'expires': 'invalid'}):
        value = copy.deepcopy(base)
        if isinstance(malformed, dict):
            value['engineering_scope'].update(malformed)
        else:
            value['engineering_scope'] = malformed
        try:
            policy(value, now=10)
            failures.append('MALFORMED_ACCEPTED')
        except PermissionError:
            pass
        except Exception as exc:
            failures.append(type(exc).__name__)
    try:
        if policy(base, now=10) != base['engineering_scope']:
            failures.append('VALID_SCOPE_CHANGED')
    except Exception:
        failures.append('VALID_SCOPE_REJECTED')
    print(json.dumps({'regression': 'engineering-policy-types-v1', 'cases': 7, 'failures': failures}), flush=True)
    return 1 if failures else 0


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ('regression', 'tests', 'canary'):
        raise PermissionError('Fixed engineering test profile required')
    job = Path(sys.argv[1])
    base = Path('/home/ibkr/.local/state/openclaw/engineering/development')
    if (job.is_symlink() or job.resolve().parent != base.resolve()
            or len(job.name) != 64 or any(c not in '0123456789abcdef' for c in job.name)):
        raise PermissionError('Fixed per-task artifact directory required')
    work = job/'worktree'; scratch = job/'tmp'
    (scratch/'home').mkdir(exist_ok=True)
    isolation = enforce(work, scratch, job/'repository/.git', sys.executable)
    if sys.argv[2] == 'canary':
        import socket
        checks = {}
        for label, path in {'credentials': '/home/ibkr/.local/state/openclaw/secretary-oauth/auth.json',
                'production_db': '/home/ibkr/.local/state/openclaw/agent_secretary.sqlite3',
                'host_proc': '/proc/1/environ', 'outside_workspace': str(job/'canary-sentinel')}.items():
            try:
                fd = os.open(path, os.O_RDONLY); os.close(fd); checks[label] = False
            except PermissionError:
                checks[label] = True
        try:
            fd = os.open(job/'canary-sentinel', os.O_WRONLY); os.close(fd); checks['outside_write'] = False
        except PermissionError:
            checks['outside_write'] = True
        try:
            sock = socket.socket(); sock.close(); checks['network'] = False
        except PermissionError:
            checks['network'] = True
        try:
            os.kill(os.getppid(), 0); checks['peer_signals'] = False
        except PermissionError:
            checks['peer_signals'] = True
        try:
            os.execve('/usr/bin/true', ['/usr/bin/true'], {}); checks['new_exec'] = False
        except PermissionError:
            checks['new_exec'] = True
        target = work/'canary-output'; target.write_text('fabricated canary')
        checks['workspace_rw'] = target.read_text() == 'fabricated canary'
        print(json.dumps({'isolation': isolation, 'checks': checks, 'passed': all(checks.values())}), flush=True)
        return 0 if all(checks.values()) else 1
    os.chdir(work)
    os.environ.clear()
    os.environ.update(PATH='/usr/bin:/bin', HOME=str(scratch/'home'), TMPDIR=str(scratch),
        LANG='C.UTF-8', TZ='UTC', PYTHONDONTWRITEBYTECODE='1', LIVE_TRADING_ENABLED='false',
        ALLOW_PAPER_TRANSMIT='false', OPENCLAW_STATE_DIR=str(scratch/'state'))
    import tempfile
    tempfile.tempdir = str(scratch)  # Invalidate any trusted-startup cached /tmp.
    # Remove the production source from import search after loading the trusted guard.
    sys.path[:] = [str(work)] + [p for p in sys.path if p.startswith(('/usr/', '/opt/openclaw/venv/'))]
    for name in list(sys.modules):
        if name == 'reporting' or name.startswith('reporting.'):
            del sys.modules[name]
    if sys.argv[2] == 'regression':
        return regression()
    suite = unittest.defaultTestLoader.discover(str(work/'tests'), pattern='test_engineering_tasks.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
