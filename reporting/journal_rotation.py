"""Cooperative JSONL append/rename receipts; archives are evidence, never pruned."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

MAX_SEGMENT_BYTES = 128 * 1024 * 1024
MAX_RECEIPTS = 1024


class JournalEvidenceError(RuntimeError):
    pass


def _paths(path):
    return (path.with_name(path.name + '.lock'), path.with_name(path.name + '.rotation.json'),
            path.with_name(path.name + '.rotation.pending'), path.with_name(path.name + '.segments'))


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def journal_lock(path, *, writer=False, allow_pending=False):
    lock, _, pending, _ = _paths(path)
    if writer:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    else:
        try:
            fd = os.open(lock, os.O_RDONLY)
        except FileNotFoundError:
            if pending.exists() and not allow_pending:
                raise JournalEvidenceError('Incomplete rotation requires reconciliation')
            yield
            return  # Read-only legacy/shadow access must not create source files.
    with os.fdopen(fd, 'rb') as handle:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(handle, (fcntl.LOCK_EX if writer else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise JournalEvidenceError('Journal owner busy; checkpoint retained')
                time.sleep(.01)
        try:
            if pending.exists() and not allow_pending:
                raise JournalEvidenceError('Incomplete rotation requires reconciliation')
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def receipts(path, *, allow_pending=False):
    _, manifest, pending, _ = _paths(path)
    if pending.exists() and not allow_pending:
        raise JournalEvidenceError('Incomplete rotation requires reconciliation')
    try:
        with manifest.open('rb') as handle:
            raw = handle.read(1048577)
    except FileNotFoundError:
        return []
    if len(raw) > 1048576:
        raise JournalEvidenceError('Rotation receipt bound exceeded')
    data = json.loads(raw)
    entries = data.get('segments')
    if data.get('version') != 1 or not isinstance(entries, list) or len(entries) > MAX_RECEIPTS:
        raise JournalEvidenceError('Invalid rotation receipt chain')
    prior = None
    seen = set()
    for item in entries:
        old = item.get('old_inode'); new = item.get('new_inode')
        if (not all(isinstance(node, list) and len(node) == 2 and all(type(n) is int and n >= 0 for n in node) for node in (old, new))
                or old == new or (prior is not None and old != prior) or tuple(old) in seen
                or not re.fullmatch(r'[a-f0-9]{32}\.jsonl', item.get('archive', ''))
                or not re.fullmatch(r'[a-f0-9]{64}', item.get('sha256', ''))
                or type(item.get('size')) is not int or not 0 <= item['size'] <= MAX_SEGMENT_BYTES):
            raise JournalEvidenceError('Invalid rotation identity/provenance')
        seen.add(tuple(old)); prior = new
    return entries


def inode(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]


def locate(path, identity, chain):
    """Only follow exact receipt/inode/size/hash evidence, never filename guesses."""
    if path.is_symlink():
        raise JournalEvidenceError('Journal symlink refused')
    if path.is_file() and inode(path) == identity:
        return path, None
    item = next((value for value in chain if value['old_inode'] == identity), None)
    if item is None:
        raise JournalEvidenceError('Rotation segment unavailable; checkpoint retained')
    segment = _paths(path)[3] / item['archive']
    if segment.is_symlink() or not segment.is_file():
        raise JournalEvidenceError('Rotation archive missing or symlinked')
    with segment.open('rb') as handle:
        stat = os.fstat(handle.fileno())
        if [stat.st_dev, stat.st_ino] != identity or stat.st_size != item['size']:
            raise JournalEvidenceError('Rotation archive identity/size mismatch')
        if hashlib.file_digest(handle, 'sha256').hexdigest() != item['sha256']:
            raise JournalEvidenceError('Rotation archive fingerprint mismatch')
    return segment, item


def _active_state(path):
    if not path.exists():
        return {'absent': True}
    st = path.stat()
    return dict(inode=[st.st_dev, st.st_ino], size=st.st_size, mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns)


def _writer_state_path(path):
    return path.with_name(path.name + '.writer.json')


def verify_active(path):
    """Cooperative producer metadata also detects identical-byte external rewrites."""
    state_path = _writer_state_path(path)
    try:
        with state_path.open('rb') as handle:
            raw = handle.read(4097)
    except FileNotFoundError:
        return  # Legacy unowned source keeps its existing conservative boundary checks.
    if len(raw) > 4096 or json.loads(raw) != _active_state(path):
        raise JournalEvidenceError('Active journal changed outside committed producer state')


def _rotate_locked(path):
    chain = receipts(path)
    verify_active(path)
    if len(chain) >= MAX_RECEIPTS:
        raise JournalEvidenceError('Receipt capacity requires explicit reconciliation')
    with path.open('rb') as handle:
        stat = os.fstat(handle.fileno())
        if stat.st_size > MAX_SEGMENT_BYTES:
            raise JournalEvidenceError('Segment too large for bounded verified rotation')
        if stat.st_size:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b'\n':
                raise JournalEvidenceError('Partial record must be reconciled before rotation')
        handle.seek(0)
        old = [stat.st_dev, stat.st_ino]
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if chain and chain[-1]['new_inode'] != old:
        raise JournalEvidenceError('Active journal is outside approved rotation chain')
    _, manifest, pending, directory = _paths(path)
    directory.mkdir(exist_ok=True, mode=0o700)
    item = dict(old_inode=old, size=stat.st_size, sha256=digest, archive=uuid.uuid4().hex + '.jsonl')
    _save(pending, item)  # Crash leaves explicit intent; writers/readers refuse to guess.
    path.rename(directory / item['archive'])
    _sync_directory(directory)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fsync(fd)
        st = os.fstat(fd)
        item['new_inode'] = [st.st_dev, st.st_ino]
    finally:
        os.close(fd)
    _save(manifest, dict(version=1, segments=chain + [item]))
    _save(_writer_state_path(path), _active_state(path))
    pending.unlink()
    _sync_directory(path.parent)
    return item


def rotate_journal(path):
    path = Path(path)
    with journal_lock(path, writer=True):
        return _rotate_locked(path)


def append_jsonl(path, payload, *, max_bytes=100 * 1024 * 1024):
    path = Path(path)
    raw = (json.dumps(payload, sort_keys=True) + '\n').encode()
    if not 0 < max_bytes <= MAX_SEGMENT_BYTES or len(raw) > 1048576:
        raise ValueError('Journal size bound exceeded')
    with journal_lock(path, writer=True):
        chain = receipts(path)
        verify_active(path)
        if path.is_symlink():
            raise JournalEvidenceError('Journal symlink refused')
        if path.exists():
            if chain and inode(path) != chain[-1]['new_inode']:
                raise JournalEvidenceError('Active journal identity changed without receipt')
            with path.open('rb') as handle:
                size = os.fstat(handle.fileno()).st_size
                if size:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b'\n':
                        raise JournalEvidenceError('Partial tail requires reconciliation')
            if size >= max_bytes or size + len(raw) > MAX_SEGMENT_BYTES:
                _rotate_locked(path)
        elif chain:
            raise JournalEvidenceError('Active journal missing after rotation')
        if not _writer_state_path(path).exists():
            _save(_writer_state_path(path), _active_state(path))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'ab') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _save(_writer_state_path(path), _active_state(path))
