"""One host-owned metadata snapshot; never native content or execution authority."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time


class NativeDeadlineExceeded(TimeoutError):
    code = 'NATIVE_DEADLINE'


class NativeStderrBudgetExceeded(TimeoutError):
    code = 'STDERR_BUDGET'


class JournalWriteError(RuntimeError):
    code = 'JOURNAL_WRITE_FAILED'


def error_code(exc):
    for kind in (NativeDeadlineExceeded, NativeStderrBudgetExceeded, JournalWriteError):
        if isinstance(exc, kind):
            return kind.code
    return 'CLIENT_EXCEPTION'


class NativeJournal:
    MAX_BYTES = 16384
    ITEM_TAIL = 16

    def __init__(self, path, timeout):
        self.path = Path(path)
        self.last_write = 0
        self.state = {'schema_version': 1, 'phase': 'PREPARED', 'outcome': 'STARTED',
            'effective_timeout_seconds': timeout, 'started_monotonic': None,
            'deadline_monotonic': None, 'thread_id': None, 'turn_id': None,
            'acceptance_observed': False, 'completion_checkpointed': False,
            'stdin_bytes': 0, 'stdout_bytes': 0, 'stderr_bytes': 0,
            'partial_line_bytes': 0, 'messages': 0, 'items': {}, 'item_tail': [],
            'cleanup': None}
        self.persist(force=True, exclusive=True)

    def _write(self, exclusive):
        for parent in (self.path, *self.path.parents):
            if parent.is_symlink():
                if str(parent) in ('/var', '/tmp') and str(parent.resolve()) == '/private' + str(parent):
                    continue  # macOS system aliases, never an application-controlled link.
                raise PermissionError('Journal symlinks refused')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = json.dumps(self.state, sort_keys=True, allow_nan=False).encode() + b'\n'
        if len(raw) > self.MAX_BYTES:
            raise ValueError('Journal metadata budget exceeded')
        if exclusive:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        else:
            meta = self.path.lstat()
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_mode & 0o077 or meta.st_uid != os.geteuid():
                raise PermissionError('Private regular journal required')
            fd, name = tempfile.mkstemp(prefix='.native-journal-', dir=self.path.parent)
            # Preserve a failed temporary write as evidence; it is never read/replayed.
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.path)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def persist(self, *, force=False, exclusive=False):
        if not force and time.monotonic() - self.last_write < .5:
            return
        try:
            self._write(exclusive)
        except Exception:
            raise JournalWriteError('JOURNAL_WRITE_FAILED') from None
        self.last_write = time.monotonic()

    def start(self, child_pid):
        now = time.monotonic()
        self.state.update(started_monotonic=now, host_pid=os.getpid(), child_pid=child_pid,
            deadline_monotonic=now + self.state['effective_timeout_seconds'])
        self.stage('CHILD_STARTED')

    def stage(self, phase, native=None):
        self.state['phase'] = phase
        for key in ('thread_id', 'turn_id'):
            value = (native or {}).get(key)
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
                    raise ValueError('Invalid journal native identity')
                self.state[key] = value
        if phase == 'TURN_ACCEPTED':
            self.state['acceptance_observed'] = True
        if phase == 'TURN_COMPLETED':
            self.state.update(completion_checkpointed=True, outcome='NATIVE_COMPLETION_CHECKPOINTED')
        self.persist(force=True)

    def item(self, item, status):
        kind = item['type']
        key = kind + ':' + status
        self.state['items'][key] = self.state['items'].get(key, 0) + 1
        identity = item.get('id')
        safe_id = identity if isinstance(identity, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', identity) else None
        self.state['item_tail'] = (self.state['item_tail'] +
            [{'item_id': safe_id, 'type': kind, 'status': status}])[-self.ITEM_TAIL:]
        self.persist()

    def failure(self, exc):
        self.state.update(outcome='UNKNOWN', failure_code=error_code(exc),
            error_type=type(exc).__name__, failure_phase=self.state['phase'],
            failure_monotonic=time.monotonic())
        self.persist(force=True)

    def cleanup(self, result):
        self.state['cleanup'] = result
        self.state['finished_monotonic'] = time.monotonic()
        self.persist(force=True)
