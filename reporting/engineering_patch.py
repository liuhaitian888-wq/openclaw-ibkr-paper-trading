"""Fixed engineering class, isolated source preparation and patch artifacts."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import tarfile
import tempfile
import time
import tokenize

CLASS = 'engineering-policy-types-v1'
FILES = ('reporting/engineering_tasks.py', 'tests/test_engineering_tasks.py')
GUARD = '''    if not isinstance(scope, dict):
        raise PermissionError('Approved fresh one-shot engineering scope required')
    if any(type(scope.get(key)) not in (int, float) for key in ('since', 'expires')):
        raise PermissionError('Approved fresh one-shot engineering scope required')
'''


def expected_ast(content):
    """The first class permits only these two guards, preserving every old gate."""
    tree = ast.parse(content)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'policy')
    if not (isinstance(function.body[1], ast.Assign)
            and isinstance(function.body[1].targets[0], ast.Name)
            and function.body[1].targets[0].id == 'scope'):
        raise PermissionError('Approved base policy shape changed')
    guards = ast.parse('def guarded():\n'+GUARD).body[0].body
    function.body[2:2] = guards
    return ast.dump(tree, include_attributes=False)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_env(home):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'LANG': 'C.UTF-8', 'TZ': 'UTC',
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0',
        'GIT_OPTIONAL_LOCKS': '0', 'PYTHONDONTWRITEBYTECODE': '1'}


def command(argv, *, cwd, home, timeout=30, limit=100000):
    """Only the host constructs argv. Capture public artifacts, not inherited secrets."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(argv, cwd=cwd, env=clean_env(home), stdin=subprocess.DEVNULL,
            stdout=out, stderr=err, close_fds=True, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while child.poll() is None:
                if time.monotonic() >= deadline or out.tell()+err.tell() > limit:
                    raise TimeoutError('Bounded engineering child exceeded deadline/output')
                time.sleep(.05)
            out.seek(0); err.seek(0)
            return {'exit_code': child.returncode, 'stdout': out.read(limit).decode('utf-8', 'replace'),
                    'stderr': err.read(limit).decode('utf-8', 'replace')}
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=2)
            else:
                child.wait()


def prepare(source, commit, job, *, deadline=None):
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('Immutable approved source commit required')
    job = Path(job)
    if job.exists():
        raise PermissionError('Existing development workspace retained; never automatically replay')
    job.mkdir(mode=0o700, parents=True)
    repository = job/'repository'; repository.mkdir(mode=0o700)
    (job/'tmp').mkdir(mode=0o700)
    home = job/'tmp/home'; home.mkdir(mode=0o700)
    sentinel = job/'canary-sentinel'
    sentinel.write_text('fabricated isolation canary; no credential data')
    sentinel.chmod(0o600)
    archive = job/'source.tar'
    def git(args, cwd=repository):
        left = 10 if deadline is None else min(10, deadline-time.monotonic())
        if left <= 0:
            raise TimeoutError('Development source preparation deadline')
        result = command(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', *args], cwd=cwd, home=home, timeout=left)
        if result['exit_code']:
            raise RuntimeError('Local snapshot Git operation failed')
        return result['stdout']
    git(['-C', str(source), 'archive', '--format=tar', '--output='+str(archive), commit])
    if archive.stat().st_size > 64_000_000:
        raise ValueError('Source archive exceeds fixed budget')
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if len(members) > 3000:
            raise ValueError('Source file budget exceeded')
        for item in members:
            name = PurePosixPath(item.name)
            if (name.is_absolute() or '..' in name.parts or any(p in ('.git', '.secrets', '.env', 'auth.json') for p in name.parts)
                    or not (item.isfile() or item.isdir()) or item.size > 8_000_000
                    or name.suffix.lower() in ('.db', '.sqlite', '.sqlite3')):
                raise PermissionError('Snapshot contains excluded path/type')
        for item in members:
            path = repository/item.name
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(item) as src, path.open('xb') as dst:
                    dst.write(src.read())
                path.chmod(0o644)
    git(['init', '--quiet'])
    git(['add', '--all'])
    git(['-c', 'user.name=Restricted Engineering', '-c', 'user.email=engineering@invalid.local',
         'commit', '--quiet', '--no-gpg-sign', '-m', 'Approved isolated source snapshot'])
    git(['worktree', 'add', '--detach', str(job/'worktree'), 'HEAD'])
    return {'upstream_commit': commit, 'snapshot_commit': git(['rev-parse', 'HEAD']).strip(),
        'files': {name: {'sha256': digest(job/'worktree'/name),
                         'content': (job/'worktree'/name).read_text()} for name in FILES}}


def apply(job, native):
    work = Path(job)/'worktree'
    edits = native.get('edits')
    if not isinstance(edits, list) or not 1 <= len(edits) <= 2:
        raise ValueError('One or two scoped file replacements required')
    paths = []
    for edit in edits:
        if (not isinstance(edit, dict) or set(edit) != {'path', 'before_sha256', 'content'}
                or edit['path'] != FILES[0] or edit['path'] in paths
                or not isinstance(edit['content'], str) or not 1 <= len(edit['content'].encode()) <= 50000):
            raise PermissionError('Patch escaped fixed file scope')
        path = work/edit['path']
        if any(parent.is_symlink() for parent in (path, path.parent, work)) or path.stat().st_nlink != 1:
            raise PermissionError('Patch target must be a regular unlinked file')
        if digest(path) != edit['before_sha256']:
            raise ValueError('Patch base content changed')
        encoded = edit['content'].encode('utf-8')
        encoding, _ = tokenize.detect_encoding(io.BytesIO(encoded).readline)
        if encoding not in ('utf-8', 'utf-8-sig'):
            raise PermissionError('Alternate source encodings refused')
        if ast.dump(ast.parse(edit['content']), include_attributes=False) != expected_ast(path.read_text()):
            raise PermissionError('Patch changed behavior outside the approved guard transformation')
        compile(edit['content'], edit['path'], 'exec')  # Parse only; never import patched code on host.
        paths.append(edit['path'])
    for edit in edits:
        path = work/edit['path']
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, 'w') as out:
            out.write(edit['content']); out.flush(); os.fsync(out.fileno())
    result = command(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', 'diff', '--no-ext-diff', '--binary', '--', *FILES],
                     cwd=work, home=Path(job)/'tmp/home')
    if result['exit_code'] or not result['stdout']:
        raise ValueError('A reviewable nonempty patch is required')
    patch = Path(job)/'patch.diff'; patch.write_text(result['stdout']); patch.chmod(0o600)
    return {'changed_files': paths, 'patch_sha256': digest(patch), 'patch_bytes': patch.stat().st_size}


def attest(job, patch):
    """The untrusted child cannot rewrite the host-owned patch or test receipt."""
    job = Path(job).resolve(); work = job/'worktree'
    gitfile = work/'.git'
    expected = 'gitdir: '+str(job/'repository/.git/worktrees/worktree')+'\n'
    if gitfile.is_symlink() or gitfile.read_text() != expected:
        raise PermissionError('Worktree Git identity changed during tests')
    actual = command(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', 'diff', '--no-ext-diff', '--binary'],
        cwd=work, home=job/'tmp/home')
    if actual['exit_code'] or hashlib.sha256(actual['stdout'].encode()).hexdigest() != patch['patch_sha256']:
        raise PermissionError('Test child changed extra tracked content or the patch')
    others = command(['/usr/bin/git', 'ls-files', '--others'], cwd=work, home=job/'tmp/home')
    if others['exit_code'] or any(name != 'canary-output' for name in others['stdout'].splitlines()):
        raise PermissionError('Test child created extra code/artifacts in the worktree')
    return {'post_test_patch_matches': True, 'extra_source_changes': False}


def test(job, profile, *, timeout=15):
    if profile not in ('regression', 'tests', 'canary'):
        raise PermissionError('Fixed test profile required')
    launcher = Path(__file__).resolve().parents[1]/'ops/cloud/run_engineering_sandbox.py'
    return command(['/opt/openclaw/venv/bin/python', '-I', str(launcher), str(job), profile],
        cwd=job, home=Path('/home/ibkr'), timeout=min(timeout, 15), limit=150000)
