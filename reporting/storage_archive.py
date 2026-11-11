"""Finite, content-checked public-artifact copies. There is no deletion API."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

CHUNK = 1024**2
GIB = 1024**3
ALLOW = re.compile(r'(?:screening/snapshots/[A-Za-z0-9_-]{1,100}/(?:[1-9]\.json|manifest\.json)|security-directory/snapshots/[A-Za-z0-9_-]{1,100}/(?:nasdaqlisted\.txt|otherlisted\.txt|manifest\.json))\Z')
REMOTE = r'''
import base64,json,os,pathlib,re,stat,sys
request=json.loads(sys.stdin.read(4096))
relative=request['path'];offset=request.get('offset');length=request.get('length',0)
allowed=re.compile(r'(?:screening/snapshots/[A-Za-z0-9_-]{1,100}/(?:[1-9]\.json|manifest\.json)|security-directory/snapshots/[A-Za-z0-9_-]{1,100}/(?:nasdaqlisted\.txt|otherlisted\.txt|manifest\.json))\Z')
if not isinstance(relative,str) or not allowed.fullmatch(relative):raise PermissionError('Public artifact allowlist required')
root=pathlib.Path('/home/ibkr/.local/state/openclaw');path=root
for part in pathlib.Path(relative).parts:
 path=path/part
 if path.is_symlink():raise PermissionError('Symlink refused')
def identity(st):return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]
with path.open('rb') as handle:
 before=os.fstat(handle.fileno())
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise PermissionError('Single regular source required')
 if offset is None:data=None
 else:
  if type(offset) is not int or type(length) is not int or offset<0 or not 1<=length<=1048576:raise ValueError('Bounded range required')
  handle.seek(offset);data=handle.read(length)
 after=os.fstat(handle.fileno())
 if identity(before)!=identity(after):raise RuntimeError('Source changed during read')
 print(json.dumps({'identity':identity(after),'size':after.st_size,'data':base64.b64encode(data).decode() if data is not None else None}))
'''


def allowed(relative):
    return isinstance(relative, str) and bool(ALLOW.fullmatch(relative))


class SSHSource:
    def __init__(self, target, key, known_hosts):
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*', target):
            raise ValueError('Explicit SSH user/host required')
        self.args = ['ssh', '-i', str(key), '-o', 'UserKnownHostsFile='+str(known_hosts),
            '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', target,
            'sudo -u ibkr python3 -c '+shlex.quote(REMOTE)]

    def fetch(self, relative, offset=None, length=0):
        if not allowed(relative):
            raise PermissionError('Live/internal/history sources excluded')
        result = subprocess.run(self.args, input=json.dumps(dict(path=relative, offset=offset, length=length)),
            text=True, capture_output=True, timeout=20)
        if result.returncode or len(result.stdout) > 2*CHUNK:
            raise ConnectionError('Bounded source read unavailable; no automatic retry')
        value = json.loads(result.stdout)
        value['bytes'] = base64.b64decode(value.pop('data'), validate=True) if value.get('data') is not None else None
        return value


def safe(root, relative):
    root = Path(root).absolute()
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Contained archive path required')
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink():
            raise ValueError('Archive parent symlink refused')
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Archive symlink refused')
    return path


class Archive:
    def __init__(self, root, *, quota=5*GIB, free_floor=100*GIB):
        self.root = Path(root).absolute()
        self.quota = quota
        self.free_floor = free_floor
        if type(quota) is not int or type(free_floor) is not int or quota <= 0 or free_floor < 0:
            raise ValueError('Finite nonnegative target budgets required')

    def headroom(self, extra=0):
        safe(self.root, 'archive.lock')
        existing = self.root
        while not existing.exists():
            existing = existing.parent
        if shutil.disk_usage(existing).free-extra < self.free_floor:
            raise OSError('Local archive free-space floor would be violated')
        total = entries = 0
        if self.root.exists():
            pending = [self.root]
            start = time.monotonic()
            while pending:
                with os.scandir(pending.pop()) as children:
                    for child in children:
                        entries += 1
                        if entries > 10_000 or time.monotonic()-start > .5:
                            raise TimeoutError('Local archive quota inventory incomplete')
                        if child.is_symlink():
                            raise ValueError('Archive symlink refused')
                        if child.is_dir(follow_symlinks=False):
                            pending.append(Path(child.path))
                        else:
                            total += child.stat(follow_symlinks=False).st_size
        if total+extra > self.quota:
            raise OSError('Local archive total quota would be exceeded')
        return dict(used_bytes=total, quota_bytes=self.quota, free_floor_bytes=self.free_floor)

    @contextmanager
    def lock(self):
        safe(self.root, 'archive.lock')
        self.headroom(2*CHUNK)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with safe(self.root, 'archive.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def save(self, job):
        raw = json.dumps(job, separators=(',', ':'), allow_nan=False)
        if len(raw.encode()) > CHUNK:
            raise ValueError('Archive manifest exceeds budget')
        path = safe(self.root, 'jobs/'+job['id']+'.json')
        path.parent.mkdir(exist_ok=True, mode=0o700)
        temporary = safe(self.root, 'jobs/'+job['id']+'.tmp')
        with temporary.open('w') as handle:
            os.chmod(temporary, 0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)

    def load(self, identity):
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('Archive job ID required')
        path = safe(self.root, 'jobs/'+identity+'.json')
        if path.stat().st_size > CHUNK:
            raise ValueError('Archive manifest exceeds budget')
        data = json.loads(path.read_text())
        if data.get('version') != 1 or data.get('id') != identity or len(data.get('files', [])) > 32:
            raise ValueError('Archive manifest identity invalid')
        for item in data['files']:
            if not allowed(item['path']) or len(item.get('chunks', [])) > 512:
                raise ValueError('Archive source/chunk budget invalid')
        return data

    def plan(self, source, paths, *, execute=False):
        if not 1 <= len(paths) <= 32 or len(set(paths)) != len(paths) or any(not allowed(p) for p in paths):
            raise PermissionError('Explicit bounded public-artifact paths required')
        self.headroom()
        files = []
        for path in paths:
            meta = source.fetch(path)
            if not 0 <= meta['size'] <= 512*CHUNK:
                raise ValueError('Source file exceeds bounded archive scope')
            files.append(dict(path=path, identity=meta['identity'], size=meta['size'], chunks=[]))
        size = sum(item['size'] for item in files)
        self.headroom(size*2+2*CHUNK)  # chunks plus quarantine restore, not cloud reclaim.
        identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        job = dict(version=1, id=identity, state='PLANNED', created_at=time.time(), files=files,
            logical_bytes=size, source_deletion_allowed=False, restored=False, batches=[])
        if execute:
            with self.lock():
                path = safe(self.root, 'jobs/'+identity+'.json')
                if path.exists():
                    return self.load(identity)
                self.save(job)
        return job

    def batch(self, source, identity, *, max_bytes=16*CHUNK, seconds=45):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 128*CHUNK or not 1 <= seconds <= 60:
            raise ValueError('Finite batch budgets required')
        with self.lock():
            job = self.load(identity)
            if job['state'] == 'NEEDS_RECONCILIATION':
                raise ValueError('Explicit source/chunk reconciliation required; no silent resume')
            if job['state'] == 'RESTORE_VERIFIED':
                return job
            used = deduplicated = 0
            start = time.monotonic()
            try:
                for item in job['files']:
                    offset = sum(chunk['bytes'] for chunk in item['chunks'])
                    while offset < item['size'] and used < max_bytes and time.monotonic()-start < seconds:
                        length = min(CHUNK, max_bytes-used, item['size']-offset)
                        reply = source.fetch(item['path'], offset, length)
                        data = reply['bytes']
                        if reply['identity'] != item['identity'] or len(data) != length:
                            raise RuntimeError('Source identity changed; retain partial job for reconciliation')
                        digest = hashlib.sha256(data).hexdigest()
                        path = safe(self.root, 'chunks/'+digest)
                        path.parent.mkdir(exist_ok=True, mode=0o700)
                        if path.exists():
                            with path.open('rb') as handle:
                                existing = handle.read(CHUNK+1)
                            if hashlib.sha256(existing).hexdigest() != digest or len(existing) != length:
                                raise RuntimeError('Existing chunk corrupt; retained without overwrite')
                            deduplicated += length
                        else:
                            self.headroom(length+2*CHUNK)
                            with path.open('xb') as handle:
                                os.chmod(path, 0o600)
                                handle.write(data)
                                handle.flush()
                                os.fsync(handle.fileno())
                        if len(item['chunks']) >= 512:
                            raise ValueError('Per-file chunk budget exceeded')
                        item['chunks'].append(dict(sha256=digest, bytes=length))
                        offset += length
                        used += length
                        self.save(job)  # resume checkpoint only after checksum and durable chunk.
                complete = all(sum(c['bytes'] for c in f['chunks']) == f['size'] for f in job['files'])
                job['state'] = 'COPIED' if complete else 'PARTIAL'
            except (TimeoutError, ConnectionError, subprocess.TimeoutExpired) as exc:
                job['state'] = 'PARTIAL'
                job['error_type'] = type(exc).__name__
                self.save(job)
                raise
            except Exception as exc:
                job['state'] = 'NEEDS_RECONCILIATION'
                job['error_type'] = type(exc).__name__
                self.save(job)
                raise
            job['batches'] = (job['batches']+[dict(at=time.time(), bytes_read=used, deduplicated_bytes=deduplicated)])[-128:]
            self.save(job)
            return job

    def verify_restore(self, identity, *, max_bytes=32*CHUNK):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 32*CHUNK:
            raise ValueError('Bounded restore verification required')
        with self.lock():
            job = self.load(identity)
            if job['state'] not in ('COPIED', 'RESTORE_VERIFIED') or job['logical_bytes'] > max_bytes:
                raise ValueError('Complete bounded copy required for explicit restore verification')
            self.headroom(job['logical_bytes']+2*CHUNK)
            for item in job['files']:
                target = safe(self.root, 'verified-restores/'+identity+'/'+item['path'])
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                full = hashlib.sha256()
                total = 0
                # Existing restore output must validate, never silently overwrite.
                if target.exists():
                    if target.stat().st_size != item['size']:
                        raise ValueError('Existing restore size differs; retained for reconciliation')
                    with target.open('rb') as old:
                        old_digest = hashlib.file_digest(old, 'sha256').hexdigest()
                    if item.get('restored_sha256') != old_digest:
                        raise ValueError('Existing restore differs; retained for reconciliation')
                else:
                    with target.open('xb') as output:
                        os.chmod(target, 0o600)
                        for chunk in item['chunks']:
                            if not re.fullmatch('[0-9a-f]{64}', chunk['sha256']):
                                raise ValueError('Chunk identity invalid')
                            with safe(self.root, 'chunks/'+chunk['sha256']).open('rb') as handle:
                                data = handle.read(CHUNK+1)
                            if len(data) != chunk['bytes'] or hashlib.sha256(data).hexdigest() != chunk['sha256']:
                                raise ValueError('Chunk checksum mismatch')
                            output.write(data)
                            full.update(data)
                            total += len(data)
                        output.flush()
                        os.fsync(output.fileno())
                    if total != item['size']:
                        raise ValueError('Restored byte count mismatch')
                    item['restored_sha256'] = full.hexdigest()
                    self.save(job)
            job.update(state='RESTORE_VERIFIED', restored=True)
            self.save(job)
            return job

    def cleanup_dry_run(self, identity):
        job = self.load(identity)
        return dict(mode='DRY_RUN_ONLY', deletion_api=False, approved_reclaim_bytes=0,
            candidates=[dict(path=f['path'], bytes=f['size'], copy_state=job['state'],
                action='RETAIN_SOURCE', blockers=['reference/provenance reconciliation', 'explicit itemized owner cleanup approval']) for f in job['files']],
            protected=['live SQLite/WAL/SHM', 'order/risk/task state', 'UNKNOWN and receipts',
                'OAuth/credentials', 'all historical backups/migration/source evidence'])
