"""Optional-write budgets only. Never blocks or prunes core financial state."""
import fcntl
import json
import os
from pathlib import Path
import time

from .database_console import contained

GIB = 1024**3
MIB = 1024**2
CLASSES = {
    'PUBLIC_SCREENING': ('screening/snapshots', 256*MIB, 64*MIB),
    'PUBLIC_DIRECTORY': ('security-directory', 64*MIB, 8*MIB),
}
POLICY = dict(version=1, approved=True, enabled=True, grants_trading_permission=False,
    minimum_free_bytes=8*GIB, minimum_free_fraction=.28)
ENGINEERING_RESERVE = 128*MIB


def load(root):
    path = contained(root, 'runtime/storage-policy.json')
    if not path.exists():
        return None
    if path.stat().st_size > 4096:
        raise ValueError('Storage policy exceeds budget')
    data = json.loads(path.read_text())
    if (set(data) != set(POLICY) or type(data.get('version')) is not int or data.get('version') != 1
            or data.get('approved') is not True or data.get('enabled') is not True
            or data.get('grants_trading_permission') is not False
            or type(data['minimum_free_bytes']) is not int or data['minimum_free_bytes'] < 8*GIB
            or type(data['minimum_free_fraction']) not in (int, float)
            or not .28 <= data['minimum_free_fraction'] <= .5):
        raise ValueError('Approved conservative nontrading storage policy required')
    return data


def usage(root, relative, *, budget=.05, limit=2000):
    folder = contained(root, relative)
    if not folder.exists():
        return 0
    start = time.monotonic()
    pending = [folder]
    total = entries = 0
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                entries += 1
                if entries > limit or time.monotonic()-start > budget:
                    raise TimeoutError('Optional quota inventory incomplete')
                if child.is_symlink():
                    raise ValueError('Optional artifact symlink refused')
                if child.is_dir(follow_symlinks=False):
                    pending.append(Path(child.path))
                else:
                    total += child.stat(follow_symlinks=False).st_size
    return total


def decision(root, kind, *, disk=None):
    if kind not in CLASSES:
        raise PermissionError('Core/unknown storage is not an optional-write class')
    policy = load(root)
    if policy is None:
        return dict(kind=kind, allowed=True, state='POLICY_UNARMED')
    st = os.statvfs(root) if disk is None else disk
    available, total = st.f_bavail*st.f_frsize, st.f_blocks*st.f_frsize
    relative, quota, reserve = CLASSES[kind]
    used = usage(root, relative)
    space = available-reserve >= max(policy['minimum_free_bytes'], total*policy['minimum_free_fraction'])
    return dict(kind=kind, allowed=space and used+reserve <= quota,
        state='ALLOWED' if space and used+reserve <= quota else 'DEFERRED_CAPACITY' if not space else 'DEFERRED_CLASS_QUOTA',
        available_bytes=available, total_bytes=total, class_bytes=used, quota_bytes=quota,
        next_run_reserve_bytes=reserve, sampled_at=time.time(), grants_trading_permission=False)


def _audit(root, value):
    """128 fixed numeric/status events, <=64KiB; only our v1 log is replaced."""
    lock = contained(root, 'runtime/storage-budget-events.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = contained(root, 'runtime/storage-budget-events.json')
        if path.exists():
            if path.stat().st_size > 64*1024:
                raise ValueError('Storage audit exceeds budget')
            data = json.loads(path.read_text())
            if data.get('version') != 1:
                raise ValueError('Existing unrelated log refused')
        else:
            data = dict(version=1, current={}, events=[])
        prior = data['current'].get(value['kind'], {})
        data['current'][value['kind']] = value
        if prior.get('state') != value['state'] or time.time()-prior.get('archived_at', 0) >= 3600:
            value = dict(value, archived_at=time.time())
            data['current'][value['kind']] = value
            data['events'] = (data['events']+[value])[-128:]
        else:
            data['current'][value['kind']]['archived_at'] = prior.get('archived_at')
        raw = json.dumps(data, separators=(',', ':'), allow_nan=False)
        if len(raw.encode()) > 64*1024:
            raise ValueError('Storage audit exceeds budget')
        temporary = contained(root, 'runtime/storage-budget-events.json.tmp')
        with temporary.open('w') as out:
            os.chmod(temporary, 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(path)


def preflight(root, kind):
    try:
        value = decision(root, kind)
        if value['state'] != 'POLICY_UNARMED':
            _audit(root, value)
        return value
    except (OSError, ValueError, TimeoutError):
        # A failed optional preflight never authorizes new bytes or core cleanup.
        return dict(kind=kind, allowed=False, state='DEFERRED_CAPACITY_UNKNOWN', grants_trading_permission=False)


def write_blob(root, kind, path, raw):
    """Guard each new public artifact; never replace differing prior evidence."""
    root=Path(root).absolute()
    relative=Path(path).absolute().relative_to(root)
    target=contained(root,relative)
    prefix,quota,_=CLASSES[kind]
    if not relative.as_posix().startswith(prefix+'/'):
        raise PermissionError('Artifact class/path mismatch')
    maximum=5*MIB if kind=='PUBLIC_SCREENING' else 2*MIB
    if not isinstance(raw,bytes) or len(raw)>maximum:
        raise ValueError('Public artifact byte budget exceeded')
    if load(root) is not None:
        gate=decision(root,kind)
        if not gate['allowed'] or gate['class_bytes']+len(raw)>quota:
            raise OSError('Optional artifact write withheld by storage budget')
        if target.exists():
            if target.stat().st_size>maximum:
                raise ValueError('Existing public evidence exceeds budget')
            with target.open('rb') as prior:
                previous=prior.read(maximum+1)
            if previous!=raw:
                raise ValueError('Differing prior evidence retained without overwrite')
            return 'DEDUPLICATED'
    with target.open('wb') as handle:
        handle.write(raw)
    return 'WRITTEN'


def read(root):
    try:
        path = contained(root, 'runtime/storage-budget-events.json')
        if not path.is_file():
            return dict(state='NOT_OBSERVED', current={})
        if path.stat().st_size > 64*1024:
            return dict(state='UNKNOWN', current={})
        data = json.loads(path.read_text())
        if data.get('version') != 1:
            raise ValueError('Unknown storage audit')
        return dict(state='RECORDED', current=data['current'], event_count=len(data['events']))
    except (OSError, ValueError, KeyError, TypeError):
        return dict(state='UNKNOWN', current={})


def engineering_decision(root, *, disk=None):
    policy = load(root)
    if policy is None:
        return dict(kind='ENGINEERING_SNAPSHOT', allowed=True, state='POLICY_UNARMED')
    st = os.statvfs(root) if disk is None else disk
    available, total = st.f_bavail*st.f_frsize, st.f_blocks*st.f_frsize
    used = usage(root,'engineering/development',budget=.05,limit=20000)
    space = available-ENGINEERING_RESERVE >= max(policy['minimum_free_bytes'],total*policy['minimum_free_fraction'])
    quota = used+ENGINEERING_RESERVE <= 512*MIB
    return dict(kind='ENGINEERING_SNAPSHOT',allowed=space and quota,
        state='ALLOWED' if space and quota else 'DEFERRED_CAPACITY' if not space else 'DEFERRED_CLASS_QUOTA',
        available_bytes=available,total_bytes=total,class_bytes=used,next_run_reserve_bytes=ENGINEERING_RESERVE,
        quota_bytes=512*MIB,sampled_at=time.time(),grants_trading_permission=False)


def engineering_preflight(root):
    try:
        value = engineering_decision(root)
        if value['state'] != 'POLICY_UNARMED': _audit(root,value)
        return value
    except (OSError,ValueError,TimeoutError):
        return dict(kind='ENGINEERING_SNAPSHOT',allowed=False,state='DEFERRED_CAPACITY_UNKNOWN')


def publication_decision(root, *, input_bytes, source_bundle_bytes, extra_bytes=0, disk=None):
    """Explicit sole-publisher preflight; no backup is skipped or deleted."""
    if any(type(x) is not int or not 0 <= x <= GIB for x in (input_bytes,source_bundle_bytes,extra_bytes)):
        raise ValueError('Finite explicit publisher byte estimates required')
    required = sum(contained(root,p).stat().st_size for p in ('runtime/recovery.sqlite3','agent_secretary.sqlite3'))
    st = os.statvfs(root) if disk is None else disk
    available = st.f_bavail*st.f_frsize
    projected = required+2*input_bytes+source_bundle_bytes+extra_bytes+8*MIB
    peak = max(GIB,3*required+input_bytes)
    allowed = projected <= 256*MIB and available > peak and available-projected >= 2*GIB
    return dict(kind='PUBLICATION_ARTIFACTS',allowed=allowed,state='ALLOWED' if allowed else 'DEFERRED_PUBLICATION_BUDGET',
        available_bytes=available,required_backup_bytes=required,projected_bytes=projected,
        wave_budget_bytes=256*MIB,original_peak_guard_bytes=peak,post_wave_floor_bytes=2*GIB,
        source_estimates_must_be_rechecked=True,grants_cleanup_permission=False,grants_trading_permission=False)


def observe(root, coordinator):
    """Called solely by the existing capacity sampler owner."""
    if load(root) is None:
        coordinator.observe('OPTIONAL_STORAGE_WRITES','PAUSED',freshness='UNKNOWN',enabled=False,reason='Optional budget policy unarmed; no business permission')
        return
    values = [decision(root, kind) for kind in CLASSES]
    good = all(value['allowed'] for value in values)
    coordinator.observe('OPTIONAL_STORAGE_WRITES', 'HEALTHY' if good else 'PAUSED',
        freshness='FRESH', enabled=True, reason='Optional public-source write budget; core state exempt',
        decisions=values, grants_trading_permission=False)
