"""Verified evidence bundles and isolated candidate restoration, no cursor writes."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

from .journal_rotation import (JournalEvidenceError, MAX_SEGMENT_BYTES, _paths, _save,
    _sync_directory, _active_state, _writer_state_path, journal_lock)

MAX_TOTAL_BYTES=2*1024*1024*1024
MAX_FILES=8192


def _digest(path):
    if path.is_symlink() or not path.is_file():raise JournalEvidenceError('Missing or symlinked backup evidence')
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def _reserve_space(parent, size):
    usage=shutil.disk_usage(parent)
    if size>MAX_TOTAL_BYTES or usage.free-size<usage.total*.20:
        raise JournalEvidenceError('Insufficient reserve space for bounded evidence bundle')


def journal_present(path):
    values=(path,*_paths(path)[1:],_writer_state_path(path),path.with_name(path.name+'.recovery'))
    if any(value.is_symlink() for value in values):raise JournalEvidenceError('Symlink journal evidence refused')
    return any(value.exists() for value in values)


def _sync_tree_directories(root):
    directories=[value for value in root.rglob('*') if value.is_dir()]
    for value in sorted(directories,key=lambda p:len(p.parts),reverse=True):_sync_directory(value)
    _sync_directory(root);_sync_directory(root.parent)


def backup_journal(path, target):
    path=Path(path);target=Path(target)
    if not journal_present(path):return dict(status='MISSING_NO_JOURNAL')
    if target.exists() or target.resolve().is_relative_to(path.parent.resolve()):
        raise JournalEvidenceError('Backup needs a new destination outside the source directory')
    with journal_lock(path,allow_pending=True):
        files=[value for value in (path,_paths(path)[1],_paths(path)[2],_writer_state_path(path)) if value.exists()]
        for directory in (_paths(path)[3],path.with_name(path.name+'.recovery')):
            if directory.exists():
                if directory.is_symlink():raise JournalEvidenceError('Symlink evidence directory refused')
                for value in directory.rglob('*'):
                    if value.is_symlink():raise JournalEvidenceError('Symlink evidence refused')
                    if value.is_file():files.append(value)
                    if len(files)>MAX_FILES:raise JournalEvidenceError('Evidence file count bound exceeded')
        inventory=[];total=0
        for value in files:
            if value.is_symlink():raise JournalEvidenceError('Symlink source refused')
            st=value.stat()
            if st.st_size>MAX_SEGMENT_BYTES:raise JournalEvidenceError('Evidence file exceeds size bound')
            total+=st.st_size
            inventory.append(dict(path=value.relative_to(path.parent).as_posix(),size=st.st_size,inode=[st.st_dev,st.st_ino],source_state=_active_state(value)))
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        _reserve_space(target.parent,total)
        target.mkdir(mode=0o700); payload=target/'payload';payload.mkdir(mode=0o700)
        for value,item in zip(files,inventory):
            copied=payload/item['path'];copied.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with value.open('rb') as src,copied.open('xb') as dst:
                shutil.copyfileobj(src,dst,length=1024*1024);dst.flush();os.fsync(dst.fileno())
            copied.chmod(0o600)
            if copied.stat().st_size!=item['size']:raise JournalEvidenceError('Source changed during backup')
            item['sha256']=_digest(copied)
            if _active_state(value)!=item['source_state'] or _digest(value)!=item['sha256']:raise JournalEvidenceError('Source changed during backup')
        manifest=dict(version=1,name=path.name,source=str(path.absolute()),files=inventory,total_bytes=total,
            pending_rotation=_paths(path)[2].exists(),candidate_only=True)
        _sync_tree_directories(target)
        _save(target/'manifest.json',manifest)  # No completion marker before all verified copies.
        return dict(status='BACKED_UP',files=len(inventory),bytes=total,approval_token=_digest(target/'manifest.json'))


def inspect_backup(backup):
    backup=Path(backup);manifest_path=backup/'manifest.json'
    if backup.is_symlink() or (backup/'payload').is_symlink() or manifest_path.is_symlink():raise JournalEvidenceError('Symlink bundle root refused')
    with manifest_path.open('rb') as handle:raw=handle.read(4*1024*1024+1)
    if manifest_path.is_symlink() or len(raw)>4*1024*1024:raise JournalEvidenceError('Invalid backup manifest')
    manifest=json.loads(raw);files=manifest.get('files');name=manifest.get('name')
    if (manifest.get('version')!=1 or not isinstance(files,list) or len(files)>MAX_FILES
            or not isinstance(name,str) or Path(name).name!=name or not name.endswith('.jsonl')):
        raise JournalEvidenceError('Invalid backup inventory')
    seen=set();identities=set();total=0
    for item in files:
        relative=PurePosixPath(item['path'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or str(relative) in seen:
            raise JournalEvidenceError('Unsafe or duplicate evidence path')
        if (type(item.get('size')) is not int or not 0<=item['size']<=MAX_SEGMENT_BYTES):
            raise JournalEvidenceError('Invalid evidence size')
        identity=item.get('inode')
        if (not isinstance(identity,list) or len(identity)!=2
                or not all(type(v) is int and v>=0 for v in identity) or tuple(identity) in identities):
            raise JournalEvidenceError('Invalid or ambiguous source inode mapping')
        identities.add(tuple(identity))
        seen.add(str(relative));total+=item['size']
        if total>MAX_TOTAL_BYTES:raise JournalEvidenceError('Evidence total size bound exceeded')
        file=backup/'payload'/str(relative)
        if not file.resolve().is_relative_to((backup/'payload').resolve()):raise JournalEvidenceError('Evidence path escapes bundle')
        current=backup/'payload'
        for part in relative.parts:
            current=current/part
            if current.is_symlink():raise JournalEvidenceError('Symlink backup component refused')
        if file.stat().st_size!=item['size'] or _digest(file)!=item['sha256']:
            raise JournalEvidenceError('Evidence fingerprint mismatch')
    if total!=manifest.get('total_bytes'):raise JournalEvidenceError('Evidence byte total mismatch')
    return dict(manifest=manifest,approval_token=hashlib.sha256(raw).hexdigest())


def restore_journal(backup, target, approval_token):
    backup=Path(backup);target=Path(target)
    inspected=inspect_backup(backup)
    if inspected['approval_token']!=approval_token:raise JournalEvidenceError('Backup approval token is stale')
    if target.exists() or target.resolve().is_relative_to(backup.resolve()):
        raise JournalEvidenceError('Restore requires a new isolated target')
    manifest=inspected['manifest'];target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    _reserve_space(target.parent,manifest['total_bytes']*2)
    target.mkdir(mode=0o700);originals=target/'originals';candidate=target/'candidate'
    originals.mkdir(mode=0o700);candidate.mkdir(mode=0o700)
    mapping={}; entries={}
    for item in manifest['files']:
        relative=item['path'];source=backup/'payload'/relative;original=originals/relative;dest=candidate/relative
        original.parent.mkdir(parents=True,exist_ok=True,mode=0o700);dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        for copy in (original,dest):
            with source.open('rb') as src,copy.open('xb') as dst:
                shutil.copyfileobj(src,dst,length=1024*1024);dst.flush();os.fsync(dst.fileno())
            copy.chmod(0o600)
            if _digest(copy)!=item['sha256']:raise JournalEvidenceError('Restore fingerprint mismatch')
        entries[relative]=dest
        mapping[tuple(item['inode'])]=_active_state(dest)['inode']
    active=candidate/manifest['name']
    def mapped(value):
        try:return mapping[tuple(value)]
        except (KeyError,TypeError):raise JournalEvidenceError('Missing restored inode evidence')
    receipt=_paths(active)[1];pending=_paths(active)[2];writer=_writer_state_path(active)
    if receipt.exists():
        value=json.loads(receipt.read_text())
        for segment in value['segments']:
            segment['old_inode']=mapped(segment['old_inode']);segment['new_inode']=mapped(segment['new_inode'])
        _save(receipt,value)
    if pending.exists():
        value=json.loads(pending.read_text());value['old_inode']=mapped(value['old_inode']);_save(pending,value)
    if writer.exists():
        value=json.loads(writer.read_text())
        if value.get('absent') is not True:
            value['inode']=mapped(value['inode'])
            original_item=next((item for item in manifest['files'] if item['path']==manifest['name']),None)
            original_state=json.loads((originals/writer.name).read_text())
            if active.exists() and original_item and original_state==original_item['source_state']:
                value=_active_state(active)
        _save(writer,value)
    result=dict(status='ISOLATED_CANDIDATE',journal=str(active),approval_token=approval_token,
        inode_map=[dict(original=list(old),restored=new) for old,new in mapping.items()],production_activated=False,
        cursor_updated=False,originals_preserved=True)
    _sync_tree_directories(target)
    _save(target/'source-manifest.json',manifest)
    _save(target/'restore-map.json',result)  # Completion proof is last; partial directories are never activated.
    _sync_directory(target)
    return result
