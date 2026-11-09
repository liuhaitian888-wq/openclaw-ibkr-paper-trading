"""Content-addressed report snapshots. The publisher owns mutable latest files.

The queue owns these immutable snapshots; no retention/deletion policy is implied.
"""
import hashlib
import os
from pathlib import Path


def freeze(directory, source, expected):
    directory=Path(directory).resolve();source=Path(source).resolve();source.relative_to(directory)
    data=source.read_bytes()
    if not 0<len(data)<=10*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Artifact changed before immutable snapshot')
    if source.suffix=='.png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Original PNG required')
    target=directory/'immutable'/expected[:2]/(expected+source.suffix)
    target.parent.mkdir(parents=True,exist_ok=True)
    # Write and fsync a private temporary inode before exclusive publication.
    import tempfile
    descriptor,name=tempfile.mkstemp(prefix='.freeze-',dir=target.parent)
    try:
        with os.fdopen(descriptor,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,0o400)
        try:os.link(name,target)
        except FileExistsError:pass
        if target.is_symlink() or target.read_bytes()!=data:raise ValueError('Immutable artifact collision')
        fd=os.open(target.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:os.unlink(name)
    return {'path':str(target),'sha256':expected,'source_path':str(source)}


def backup(root, target):
    """Include frozen report provenance in the existing per-host backup owner."""
    import shutil
    import re
    source=Path(root)/'reports/financial/immutable';target=Path(target)/'financial-artifacts'
    if not source.exists():return {'status':'NOT_CREATED','items':[]}
    items=[];total=0
    for path in source.rglob('*'):
        if path.is_symlink():raise ValueError('Report archive symlink refused')
        if not path.is_file():continue
        if path.name.startswith('.freeze-'):continue
        if len(items)>=10000:raise ValueError('Report backup file budget exceeded')
        size=path.stat().st_size;total+=size
        if not 0<size<=10*1024*1024 or total>1024**3:raise ValueError('Report backup byte budget exceeded')
        if not re.fullmatch(r'[0-9a-f]{64}\.(?:png|json)',path.name):raise ValueError('Unrecognized immutable report artifact')
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=path.stem:raise ValueError('Immutable source differs from its identity')
        destination=target/path.relative_to(source);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination)
        with destination.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=digest:raise ValueError('Report backup verification failed')
        items.append({'file':str(destination.relative_to(target)),'sha256':digest,'bytes':size})
    return {'status':'BACKED_UP','items':items,'bytes':total,'legacy_mutable_reports_included':False}
