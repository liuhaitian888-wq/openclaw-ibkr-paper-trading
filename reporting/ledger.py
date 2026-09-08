"""Fsynced JSON ledger, derived from the deployed report_delivery_guard.save/flock.

Same durable JSON model; explicit sandbox namespace, incidents and audit events.
No production file is migrated automatically.
"""
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from .errors import redact

class Busy(Exception):pass

def save(path,payload):
    path=Path(path);temporary=path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(payload,stream,sort_keys=True,ensure_ascii=False)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

class Ledger:
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/'delivery.json'
    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        with (self.directory/'delivery.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise Busy() from exc
            yield
    def read(self):
        if not self.path.exists():return {'schema_version':2,'reports':{},'incidents':{},'events':[]}
        state=json.loads(self.path.read_text())
        if state.get('schema_version')!=2:raise ValueError('Legacy ledger requires explicit reconciliation/migration; no automatic overwrite')
        return state
    def commit(self,state):
        save(self.path,redact(state))
        if self.read()!=redact(state):raise OSError('Ledger readback mismatch')
    def event(self,state,name,now,**details):
        state['events'].append({'event':name,'timestamp':now.isoformat(),**redact(details)})
    def incident(self,state,key,error,now):
        previous=state['incidents'].get(key)
        if previous:
            previous.update(last_seen=now.isoformat(),occurrences=previous['occurrences']+1,error=error)
        else:state['incidents'][key]={'local_only':True,'first_seen':now.isoformat(),'last_seen':now.isoformat(),'occurrences':1,'error':error}

    def migrate_v2(self,now):
        """Explicit additive migration under the same production lock; retain every legacy byte in backup."""
        import hashlib
        import copy
        with self.locked():
            original=self.path.read_bytes()
            state=json.loads(original)
            if state.get('schema_version')==2:return {'already_v2':True}
            if state.get('schema_version') not in (None,1):raise ValueError('Unsupported ledger schema')
            if not isinstance(state.get('reports'),dict):raise ValueError('Invalid legacy reports')
            for key,expected in [('incidents',dict),('events',list)]:
                if key in state and not isinstance(state[key],expected):raise ValueError('Invalid legacy '+key)
            digest=hashlib.sha256(original).hexdigest()
            backup=self.directory/('delivery.pre-v2.'+digest+'.json')
            if backup.exists():
                if backup.read_bytes()!=original:raise OSError('Backup conflict')
            else:
                with backup.open('xb') as f:f.write(original);f.flush();os.fsync(f.fileno())
            fd=os.open(self.directory,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            upgraded=copy.deepcopy(state)
            upgraded.update(schema_version=2)
            upgraded.setdefault('incidents',{});upgraded.setdefault('events',[])
            upgraded['events'].append({'event':'legacy_migration','timestamp':now.isoformat(),'backup_sha256':digest,'automatic_replay_allowed':False})
            # Old identities/statuses and incident histories remain exact, including pending/UNKNOWN.
            save(self.path,upgraded)
            readback=self.read()
            for k,v in state.items():
                if k not in ('schema_version','events') and readback.get(k)!=v:raise OSError('Migration history mismatch')
            if readback!=upgraded:raise OSError('Migration readback mismatch')
            return {'backup_path':str(backup),'backup_sha256':digest,'history_preserved':True,'schema_version':2}
