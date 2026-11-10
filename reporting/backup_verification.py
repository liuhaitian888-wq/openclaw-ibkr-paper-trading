"""Offline integrity checks of existing backup exports; never a restore owner."""
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tarfile
import tempfile
import time

DATABASE_FILES = {name: Path(name).name+'.gz' for name in (
    'trading_audit.sqlite3', 'financial_ledger.sqlite3',
    'runtime/recovery.sqlite3', 'agent_secretary.sqlite3')}
MAX_ARCHIVE_BYTES = 200*1024**2
MAX_MANIFEST_BYTES = 4*1024**2
MAX_GZIP_BYTES = 50*1024**2
MAX_DB_BYTES = 512*1024**2
MAX_TOTAL_BYTES = 2*1024**3
MAX_SECONDS = 60
SQLITE_SECONDS = 20


class BackupVerificationError(Exception):
    def __init__(self, code, workdir=None):
        self.code = code
        self.workdir = str(workdir) if workdir is not None else None
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise BackupVerificationError(code)


def _deadline(limit):
    _require(time.monotonic() < limit, 'DEADLINE_EXCEEDED')


class _TimedReader:
    """Borrowed stream; the enclosing file/tar-member context owns its lifetime."""
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit

    def read(self, size=-1):
        _deadline(self.limit)
        return self.stream.read(size)

    def seek(self, *args):
        _deadline(self.limit)
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()


def _hash(stream, limit):
    digest = hashlib.sha256()
    while True:
        _deadline(limit)
        data = stream.read(1024**2)
        if not data:
            return digest.hexdigest()
        digest.update(data)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, 'DUPLICATE_JSON_KEY')
        value[key] = item
    return value


def _manifest(data, members):
    m = json.loads(data, object_pairs_hook=_unique_object)
    _require(isinstance(m, dict), 'INVALID_MANIFEST')
    _require(m.get('restore_requires_maintenance_and_broker_reconciliation') is True,
             'MISSING_RECONCILIATION_BOUNDARY')
    _require(type(m.get('cross_database_atomic')) is bool, 'INVALID_MANIFEST')
    created = m.get('created_at')
    _require(isinstance(created, str) and bool(re.fullmatch(r'\d{8}T\d{6}(?:\.\d{1,6})?Z', created)), 'INVALID_MANIFEST')
    items = m.get('items')
    _require(isinstance(items, list) and len(items) == 4, 'INCOMPLETE_BACKUP')
    seen = set()
    for item in items:
        _require(isinstance(item, dict), 'INVALID_MANIFEST')
        source = item.get('source')
        _require(isinstance(source, str) and source in DATABASE_FILES and source not in seen,
                 'AMBIGUOUS_DATABASE_IDENTITY')
        seen.add(source)
        _require(item.get('status') == 'BACKED_UP', 'INCOMPLETE_BACKUP')
        name = DATABASE_FILES[source]
        _require(item.get('file') == name, 'INVALID_MEMBER_NAME')
        size = item.get('compressed_bytes')
        _require(type(size) is int and 0 < size <= MAX_GZIP_BYTES and size == members[name].size,
                 'INVALID_COMPRESSED_SIZE')
        digest = item.get('sha256_uncompressed')
        _require(isinstance(digest, str) and bool(re.fullmatch('[a-f0-9]{64}', digest)), 'INVALID_DIGEST')
    return m


def _receipt(workdir, result):
    with (workdir/'receipt.json').open('x', encoding='utf-8') as f:
        os.chmod(workdir/'receipt.json', 0o600)
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def verify_archive(archive_path, output_root, *, expected_archive_sha256=None):
    """Return copy evidence; errors retain owned partial files and a safe receipt.

    All database paths are newly-created copies. No caller-supplied SQL, live DB
    connection, network, subprocess, deletion, or production activation exists.
    """
    limit = time.monotonic()+MAX_SECONDS
    work = None
    result = dict(verifier='offline-backup-copy-v1', state='FAILED', databases=[], source_authenticated=False,
                  cross_database_consistency_verified=False, grants_restore_permission=False,
                  live_restore_performed=False)
    try:
        archive_path, output_root = Path(archive_path), Path(output_root)
        _require(output_root.is_dir() and not output_root.is_symlink(), 'PRIVATE_OUTPUT_ROOT_REQUIRED')
        if expected_archive_sha256 is not None:
            _require(isinstance(expected_archive_sha256, str) and bool(re.fullmatch('[a-f0-9]{64}', expected_archive_sha256)), 'INVALID_ARCHIVE_DIGEST')
        try:
            fd = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            raise BackupVerificationError('ARCHIVE_NOT_REGULAR') from None
        with os.fdopen(fd, 'rb') as raw:
            meta = os.fstat(raw.fileno())
            _require(stat.S_ISREG(meta.st_mode), 'ARCHIVE_NOT_REGULAR')
            _require(0 < meta.st_size <= MAX_ARCHIVE_BYTES, 'ARCHIVE_BYTE_LIMIT')
            digest = _hash(raw, limit)
            if expected_archive_sha256 is not None:
                _require(digest == expected_archive_sha256, 'ARCHIVE_HASH_MISMATCH')
            raw.seek(0)
            work = Path(tempfile.mkdtemp(prefix='backup-check-', dir=output_root.resolve()))
            result.update(workdir=str(work), archive_sha256=digest,
                          archive_anchor_match=expected_archive_sha256 is not None)
            with tarfile.open(fileobj=_TimedReader(raw, limit), mode='r:') as archive:
                members = {}
                allowed = {'backup.json', *DATABASE_FILES.values()}
                for member in archive:
                    _deadline(limit)
                    _require(member.name in allowed and member.name not in members, 'UNEXPECTED_OR_DUPLICATE_MEMBER')
                    _require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and member.sparse is None, 'NONREGULAR_MEMBER')
                    cap = MAX_MANIFEST_BYTES if member.name == 'backup.json' else MAX_GZIP_BYTES
                    _require(0 < member.size <= cap, 'MEMBER_BYTE_LIMIT')
                    members[member.name] = member
                _require(set(members) == allowed, 'INCOMPLETE_BACKUP')
                with archive.extractfile(members['backup.json']) as f:
                    manifest = _manifest(f.read(MAX_MANIFEST_BYTES+1), members)
                result.update(source_created_at_declared=manifest['created_at'],
                              cross_database_atomic_declared=manifest['cross_database_atomic'],
                              restore_requires_reconciliation=True)
                total = 0
                for item in manifest['items']:
                    name = Path(item['source']).name  # Already matched the fixed allowlist.
                    target = work/name
                    digest_db, size = hashlib.sha256(), 0
                    with archive.extractfile(members[item['file']]) as packed:
                        with gzip.GzipFile(fileobj=_TimedReader(packed, limit)) as decoded:
                            fd_out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            with os.fdopen(fd_out, 'wb') as f:
                                while True:
                                    _deadline(limit)
                                    data = decoded.read(1024**2)
                                    if not data:
                                        break
                                    size += len(data); total += len(data)
                                    _require(size <= MAX_DB_BYTES and total <= MAX_TOTAL_BYTES, 'DECODED_BYTE_LIMIT')
                                    digest_db.update(data); f.write(data)
                                f.flush(); os.fsync(f.fileno())
                    _require(digest_db.hexdigest() == item['sha256_uncompressed'], 'HASH_MISMATCH')
                    sql_limit = min(limit, time.monotonic()+SQLITE_SECONDS)
                    # Immutable is asserted only for this fresh closed checker-owned copy.
                    with closing(sqlite3.connect(target.as_uri()+'?mode=ro&immutable=1', uri=True, timeout=.1)) as db:
                        db.execute('PRAGMA query_only=ON')
                        db.execute('PRAGMA trusted_schema=OFF')
                        db.set_progress_handler(lambda: 1 if time.monotonic() >= sql_limit else 0, 1000)
                        check = db.execute('PRAGMA quick_check').fetchall()
                        _deadline(sql_limit)
                        _require(check == [('ok',)], 'SQLITE_INVALID')
                    with target.open('rb') as f:
                        _require(_hash(f, limit) == item['sha256_uncompressed'], 'COPY_CHANGED')
                    result['databases'].append(dict(source=item['source'], file=name, bytes=size,
                                                     sha256=item['sha256_uncompressed'], quick_check='ok'))
            raw.seek(0)
            _require(_hash(raw, limit) == result['archive_sha256'], 'ARCHIVE_CHANGED')
            after = os.stat(archive_path, follow_symlinks=False)
            _require((meta.st_dev, meta.st_ino, meta.st_size) == (after.st_dev, after.st_ino, after.st_size), 'ARCHIVE_CHANGED')
        _deadline(limit)
        result.update(state='CHECKED_COPY', checked_at=datetime.now(timezone.utc).isoformat())
        _receipt(work, result)
        return result
    except Exception as exc:
        if isinstance(exc, BackupVerificationError):
            code = exc.code
        elif isinstance(exc, sqlite3.Error):
            code = 'DEADLINE_EXCEEDED' if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_INTERRUPT else 'SQLITE_INVALID'
        elif isinstance(exc, (gzip.BadGzipFile, EOFError)):
            code = 'INVALID_GZIP'
        elif isinstance(exc, (tarfile.TarError, ValueError, KeyError, TypeError)):
            code = 'INVALID_ARCHIVE_OR_MANIFEST'
        else:
            code = 'IO_FAILURE'
        if work is not None:
            result.update(state='FAILED', error_code=code)
            try:
                _receipt(work, result)
            except OSError:
                pass  # Retain original failure and partial copies; never delete to hide it.
        raise BackupVerificationError(code, work) from None
