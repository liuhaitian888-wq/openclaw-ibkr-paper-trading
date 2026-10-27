"""Explicit evidence-bound roll-forward for interrupted journal rotation only."""
import hashlib
import json
import os
from pathlib import Path
import re

from .journal_rotation import (JournalEvidenceError, MAX_SEGMENT_BYTES, _paths,
    MAX_RECEIPTS, _save, _sync_directory, _active_state, _writer_state_path, journal_lock, receipts, inode)


def _read(path, maximum=1048576):
    if path.is_symlink():raise JournalEvidenceError('Symlink evidence refused')
    with path.open('rb') as handle:raw=handle.read(maximum+1)
    if len(raw)>maximum:raise JournalEvidenceError('Evidence bound exceeded')
    return raw


def _fingerprint(path):
    if not path.exists():return {'absent':True}
    if path.is_symlink():raise JournalEvidenceError('Symlink evidence refused')
    with path.open('rb') as handle:
        st=os.fstat(handle.fileno())
        if st.st_size>MAX_SEGMENT_BYTES:raise JournalEvidenceError('Evidence bound exceeded')
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
    return dict(**_active_state(path),sha256=digest)


def _inspect_locked(path):
    _,manifest,pending,directory=_paths(path)
    raw=_read(pending)
    item=json.loads(raw)
    if (set(item)!={'old_inode','size','sha256','archive'}
            or not isinstance(item['old_inode'],list) or len(item['old_inode'])!=2
            or not all(type(x) is int and x>=0 for x in item['old_inode'])
            or type(item['size']) is not int or not 0<=item['size']<=MAX_SEGMENT_BYTES
            or not re.fullmatch('[a-f0-9]{64}',item['sha256'])
            or not re.fullmatch(r'[a-f0-9]{32}\.jsonl',item['archive'])
            or path.is_symlink() or directory.is_symlink()):
        raise JournalEvidenceError('Invalid pending identity or provenance')
    chain=receipts(path,allow_pending=True)
    found=[entry for entry in chain if entry['archive']==item['archive']]
    committed=bool(found)
    if committed:
        if len(found)!=1 or found[0]!=chain[-1] or any(found[0].get(k)!=v for k,v in item.items()):
            raise JournalEvidenceError('Pending and committed receipt disagree')
    elif chain and chain[-1]['new_inode']!=item['old_inode']:
        raise JournalEvidenceError('Pending breaks the existing receipt chain')
    if not committed and len(chain)>=MAX_RECEIPTS:
        raise JournalEvidenceError('Receipt capacity requires separate reconciliation')
    archive=directory/item['archive']
    old=archive if archive.exists() else path
    proof=_fingerprint(old)
    if (proof.get('inode')!=item['old_inode'] or proof.get('size')!=item['size']
            or proof.get('sha256')!=item['sha256']):
        raise JournalEvidenceError('Old segment identity/content is not proven')
    if archive.exists():
        if path.exists():
            if inode(path)==item['old_inode'] or path.stat().st_size!=0:
                raise JournalEvidenceError('Replacement active file is not a distinct empty file')
            if committed and found[0]['new_inode']!=inode(path):
                raise JournalEvidenceError('Committed replacement identity mismatch')
            phase='FINALIZE_COMMITTED' if committed else 'COMMIT_RECEIPT'
        else:
            if committed:raise JournalEvidenceError('Committed active file missing')
            phase='CREATE_ACTIVE'
    else:
        if committed:raise JournalEvidenceError('Committed archive missing')
        phase='FINISH_RENAME'
    writer=_writer_state_path(path)
    if writer.exists():
        state=json.loads(_read(writer,4096))
        if state!=_active_state(path) and not (state.get('inode')==item['old_inode'] and state.get('size')==item['size']):
            raise JournalEvidenceError('Producer state conflicts with pending rotation')
    witnesses={label:_fingerprint(value) for label,value in (
        ('pending',pending),('manifest',manifest),('writer',writer),('active',path),('archive',archive))}
    plan=dict(version=1,source=str(path.absolute()),phase=phase,pending=item,witnesses=witnesses)
    plan['approval_token']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return plan


def inspect_rotation(path):
    path=Path(path)
    if not _paths(path)[2].is_file():raise JournalEvidenceError('No pending rotation to reconcile')
    with journal_lock(path,allow_pending=True):return _inspect_locked(path)


def recover_rotation(path, approval_token):
    path=Path(path)
    if not re.fullmatch('[a-f0-9]{64}',approval_token):raise ValueError('Explicit inspection token required')
    proof_dir=path.with_name(path.name+'.recovery')/approval_token
    if proof_dir.parent.is_symlink() or proof_dir.is_symlink():
        raise JournalEvidenceError('Symlink recovery proof directory refused')
    _,manifest,pending,directory=_paths(path)
    with journal_lock(path,writer=True,allow_pending=True):
        if not pending.exists():
            result_path=proof_dir/'result.json'
            if not result_path.is_file():raise JournalEvidenceError('No pending rotation or matching completion proof')
            saved=json.loads(_read(result_path)); plan=json.loads(_read(proof_dir/'plan.json'))
            seed={k:v for k,v in plan.items() if k!='approval_token'}
            if (plan.get('source')!=str(path.absolute()) or plan.get('approval_token')!=approval_token
                    or hashlib.sha256(json.dumps(seed,sort_keys=True).encode()).hexdigest()!=approval_token):
                raise JournalEvidenceError('Completion proof is not bound to this inspection')
            chain=receipts(path)
            entry=next((e for e in chain if e['archive']==plan['pending']['archive']),None)
            if entry is None or any(entry[k]!=v for k,v in plan['pending'].items()):
                raise JournalEvidenceError('Completion proof no longer reconciles')
            archive=directory/entry['archive']; fingerprint=_fingerprint(archive)
            if fingerprint.get('inode')!=entry['old_inode'] or fingerprint.get('sha256')!=entry['sha256']:
                raise JournalEvidenceError('Completed source evidence changed')
            saved['status']='COMPLETED';_save(result_path,saved)
            return dict(status='ALREADY_COMPLETED',approval_token=approval_token)
        plan=_inspect_locked(path)
        if plan['approval_token']!=approval_token:raise JournalEvidenceError('Inspection token is stale; inspect again')
        proof_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        plan_path=proof_dir/'plan.json'
        if plan_path.exists() and json.loads(_read(plan_path))!=plan:
            raise JournalEvidenceError('Existing recovery proof conflicts')
        _save(plan_path,plan)
        for label,value in (('pending',pending),('manifest',manifest),('writer',_writer_state_path(path))):
            if value.exists() and not (proof_dir/(label+'.json')).exists():
                _save(proof_dir/(label+'.json'),json.loads(_read(value)))
        item=plan['pending'];archive=directory/item['archive']
        directory.mkdir(exist_ok=True,mode=0o700)
        if not archive.exists():
            path.rename(archive);_sync_directory(directory);_sync_directory(path.parent)
        if not path.exists():
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:os.fsync(fd)
            finally:os.close(fd)
        chain=receipts(path,allow_pending=True)
        if not any(e['archive']==item['archive'] for e in chain):
            _save(manifest,dict(version=1,segments=chain+[{**item,'new_inode':inode(path)}]))
        _save(_writer_state_path(path),_active_state(path))
        result=dict(status='COMMITTED_WAITING_RELEASE',approval_token=approval_token,archive=item['archive'])
        _save(proof_dir/'result.json',result)
        pending.unlink();_sync_directory(path.parent)
        result['status']='COMPLETED';_save(proof_dir/'result.json',result)
        return result
