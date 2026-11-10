"""Owned local snapshot-write circuit; never connects, sends, trades or resets budgets."""
from contextlib import closing
import json
import hashlib
import base64
import os
import sqlite3
import time
import uuid


from reporting.local_persistence import MARKER_NAME

MARKER=MARKER_NAME


class PaperPersistenceCircuit:
    def __init__(self,monitor):
        self.monitor=monitor
        self.path=monitor.coordinator.path.parent/MARKER
        self.last_probe=None
        self.failure=None
        if self.path.exists() or self.path.is_symlink():
            try:
                if self.path.is_symlink() or self.path.stat().st_size>10000:raise ValueError('Untrusted marker')
                self.failure=json.loads(self.path.read_text())
                if (self.failure.get('kind')!='PAPER_LOCAL_PERSISTENCE_FAILURE'
                        or not isinstance(self.failure.get('id'),str) or len(self.failure['id'])!=32
                        or any(c not in '0123456789abcdef' for c in self.failure['id'])):raise ValueError('Unexpected marker')
            except Exception:self.failure=dict(kind='PAPER_LOCAL_PERSISTENCE_FAILURE',id=None,requires_operator=True)
            with os.scandir(self.path.parent) as entries:
                if any(e.name.startswith('paper-persistence-evidence-'+str(self.failure.get('id'))+'-') for e in entries):
                    self.failure['requires_operator']=True
            self.monitor.state['local_persistence_failure']=dict(self.failure)

    def _sync_directory(self):
        descriptor=os.open(self.path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    @property
    def blocked(self):return self.failure is not None

    def block(self,exc,stage):
        with self.monitor.lock:
            if self.failure is None:
                self.failure=dict(kind='PAPER_LOCAL_PERSISTENCE_FAILURE',id=uuid.uuid4().hex,
                    stage=stage,observed_at=self.monitor.clock(),error_type=type(exc).__name__,
                    sqlite_errorcode=getattr(exc,'sqlite_errorcode',None),sqlite_errorname=getattr(exc,'sqlite_errorname',None),
                    requires_operator=(stage.startswith(('canonical_','native_callback:')) or
                        (getattr(exc,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)))
                try:
                    with self.path.open('x') as stream:
                        os.chmod(self.path,0o600)
                        json.dump(self.failure,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
                    self._sync_directory()
                except FileExistsError:self.failure['requires_operator']=True
                except OSError:self.failure['marker_write_failed']=True
                print(json.dumps(dict(event='PAPER_LOCAL_PERSISTENCE_BLOCKED',**self.failure),sort_keys=True),flush=True)
            self.monitor.state.update(local_persistence_failure=dict(self.failure),dirty=True,
                needs_recovery_sync=True,fault='LOCAL_PERSISTENCE_RECONCILIATION_REQUIRED')

    def defer_record(self,identity,kind,payload,observed):
        """Retain exact local callback rows, without replaying any broker action."""
        with self.monitor.lock:
            row=dict(identity=identity,kind=kind,payload=payload,observed=observed,epoch=self.monitor.state['epoch'])
            target=self.path.with_name('paper-persistence-record-'+self.failure['id']+'-'+identity+'.json')
            try:
                if target.exists():
                    old=json.loads(target.read_text())
                    if any(old[k]!=row[k] for k in ('identity','kind','payload','epoch')):raise ValueError('Deferred row differs')
                    return
                with target.open('x') as stream:
                    os.chmod(target,0o600);json.dump(row,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
                self._sync_directory()
            except Exception:
                self.failure['requires_operator']=True;self.failure['callback_evidence_unconfirmed']=True
                self.monitor.state['local_persistence_failure']=dict(self.failure)

    def _drain_records(self):
        prefix='paper-persistence-record-'+self.failure['id']+'-'
        paths=[]
        with os.scandir(self.path.parent) as entries:
            for entry in entries:
                if entry.name.startswith(prefix) and entry.name.endswith('.json'):
                    paths.append(self.path.parent/entry.name)
                    if len(paths)>=256:break
        rows=[]
        for path in paths:
            if path.is_symlink() or path.stat().st_size>1000000:raise ValueError('Untrusted deferred callback row')
            row=json.loads(path.read_text())
            if hashlib.sha256((row['epoch']+row['kind']+row['payload']).encode()).hexdigest()!=row['identity']:
                raise ValueError('Deferred callback fingerprint differs')
            rows.append(row)
        with closing(self.monitor.coordinator.connect()) as c,c:
            for row in rows:
                old=c.execute('SELECT kind,payload FROM paper_callback_events WHERE event_id=?',(row['identity'],)).fetchone()
                if old and old!=(row['kind'],row['payload']):raise ValueError('Canonical callback row differs')
                c.execute('INSERT OR IGNORE INTO paper_callback_events VALUES(?,?,?,?)',
                    (row['identity'],row['kind'],row['payload'],row['observed']))
        with closing(self.monitor.coordinator.connect()) as c:
            for row in rows:
                if c.execute('SELECT kind,payload FROM paper_callback_events WHERE event_id=?',(row['identity'],)).fetchone()!=(row['kind'],row['payload']):
                    raise RuntimeError('Deferred callback commit readback differs')
        for path in paths:path.rename(path.with_name(path.name+'.reconciled.'+uuid.uuid4().hex))
        if paths:self._sync_directory()
        with os.scandir(self.path.parent) as entries:
            return not any(e.name.startswith(prefix) and e.name.endswith('.json') for e in entries)

    def capture_callback(self,exc,stage,args,kwargs):
        """Keep opaque forensic evidence; never deserialize or replay callbacks."""
        with self.monitor.lock:
            self.block(exc,stage)
            self.failure['requires_operator']=True
            self.monitor.state['local_persistence_failure']=dict(self.failure)
            def encode(value):
                if hasattr(value,'SerializeToString'):
                    return dict(type=type(value).__name__,protobuf=base64.b64encode(value.SerializeToString()).decode())
                if hasattr(value,'__dict__'):return dict(type=type(value).__name__,fields=vars(value))
                return dict(type=type(value).__name__,value=str(value))
            try:
                content=json.dumps(dict(stage=stage,args=args,kwargs=kwargs),default=encode,allow_nan=False,sort_keys=True).encode()
                if len(content)>32000000:raise ValueError('Native evidence exceeds SDK-sized diagnostic bound')
                digest=hashlib.sha256(content).hexdigest()
                target=self.path.with_name('paper-persistence-evidence-'+self.failure['id']+'-'+digest+'.json')
                if target.exists():
                    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Evidence collision')
                else:
                    with target.open('xb') as stream:
                        os.chmod(target,0o600);stream.write(content);stream.flush();os.fsync(stream.fileno())
                    self._sync_directory()
            except Exception:self.failure['callback_evidence_unconfirmed']=True
            self.monitor.state['local_persistence_failure']=dict(self.failure)

    def poll(self,client,*,monotonic=time.monotonic):
        """Existing owner only: probe, request one fresh readback, then commit proof."""
        if not self.blocked:return False
        if self.failure.get('requires_operator') or self.failure.get('marker_write_failed'):return False
        elapsed=monotonic()
        if self.last_probe is not None and elapsed-self.last_probe<5:return False
        self.last_probe=elapsed
        if not client.isConnected() or client.accounts!=['DUQ503649']:return False
        monitor=self.monitor
        with monitor.lock:
            archive=None
            try:
                if not self.path.exists() or json.loads(self.path.read_text()).get('id')!=self.failure['id']:
                    self.failure['requires_operator']=True;return False
                if not self._drain_records():return False
                if not self.failure.get('reconciliation_requested'):
                    state=monitor.state
                    if (set(state.get('ends',[]))!={'orders','positions','executions','completed_orders'}
                            or not all(state.get(k) is True for k in ('connected','identity','upstream_connected'))
                            or not 0<=monitor.clock()-state.get('last_server_reply',0)<=10):return False
                    payload=json.dumps(dict(event='PAPER_LOCAL_PERSISTENCE_PROBE',fault_id=self.failure['id']))
                    with closing(monitor.coordinator.connect()) as c,c:
                        ident=c.execute('INSERT INTO module_events(payload) VALUES (?)',(payload,)).lastrowid
                    with closing(monitor.coordinator.connect()) as c:
                        if c.execute('SELECT payload FROM module_events WHERE id=?',(ident,)).fetchone()!=(payload,):
                            raise RuntimeError('Local write probe readback differs')
                    # No old end markers can satisfy this occurrence. This is a
                    # bounded idempotent broker READ on the already owned socket.
                    monitor.coordinator.observe('LOCAL_STATE','FAILED',freshness='STALE',
                        reason='Local snapshot journal requires fresh native reconciliation',local_persistence_failure=dict(self.failure))
                    if self.failure.get('readback_attempts',0)>=3:
                        self.failure['requires_operator']=True;return False
                    self.failure['readback_attempts']=self.failure.get('readback_attempts',0)+1
                    self.failure['probe_at']=monitor.clock()
                    self.failure['reconciliation_requested']=True
                    monitor.state.update(ends=[],dirty=True)
                    client.reconcile()
                    return False
                if monitor.clock()-self.failure['probe_at']>30:
                    self.failure['requires_operator']=True
                    print(json.dumps(dict(event='PAPER_LOCAL_PERSISTENCE_RECOVERY_UNCONFIRMED',fault_id=self.failure['id'])),flush=True)
                    return False
                if (not monitor._native_complete() or monitor.state.get('reconciled_at',0)<self.failure['probe_at']
                        or monitor.state.get('last_server_reply',0)<self.failure['probe_at']):return False
                failure=self.failure
                monitor.state.pop('local_persistence_failure',None)
                monitor.state.update(needs_recovery_sync=False,fault=None)
                try:monitor._publish_impl()
                except Exception:
                    monitor.state['local_persistence_failure']=dict(failure)
                    monitor.state.update(dirty=True,needs_recovery_sync=True,fault='LOCAL_PERSISTENCE_RECONCILIATION_REQUIRED')
                    raise
                if self.failure.get('requires_operator') or self.failure.get('callback_evidence_unconfirmed'):
                    raise RuntimeError('Recovery publication created unresolved evidence')
                if not self._drain_records():
                    self.failure['reconciliation_requested']=False
                    monitor.state['local_persistence_failure']=dict(self.failure)
                    monitor.state.update(dirty=True,needs_recovery_sync=True,fault='LOCAL_PERSISTENCE_RECONCILIATION_REQUIRED')
                    return False
                if self.failure.get('requires_operator') or self.failure.get('callback_evidence_unconfirmed'):
                    raise RuntimeError('Recovery callback commit remains unverified')
                # Preserve the original fault as provenance, never erase it.
                archive=self.path.with_name('paper-local-persistence-reconciled-'+failure['id']+'.json')
                if archive.exists():raise PermissionError('Fault archive already exists')
                self.path.rename(archive)
                self._sync_directory()
                monitor.coordinator.observe('LOCAL_STATE','HEALTHY',freshness='FRESH',
                    reason='Local journal committed and fresh native readback published',local_persistence_failure=None)
                self.failure=None
                print(json.dumps(dict(event='PAPER_LOCAL_PERSISTENCE_RECONCILED',fault_id=failure['id'])),flush=True)
                return True
            except (sqlite3.Error,OSError,ValueError,TypeError,KeyError,RuntimeError,PermissionError) as exc:
                if self.failure is not None:
                    if archive is not None and archive.exists() and not self.path.exists():
                        try:
                            archive.rename(self.path);self._sync_directory()
                        except OSError:self.failure['marker_write_failed']=True
                    if not isinstance(exc,sqlite3.Error) or (getattr(exc,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                        self.failure['requires_operator']=True
                    if isinstance(exc,sqlite3.Error) and (getattr(exc,'sqlite_errorcode',0)&255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                        self.failure['reconciliation_requested']=False
                    self.failure['last_recovery_error_type']=type(exc).__name__
                    monitor.state['local_persistence_failure']=dict(self.failure)
                    monitor.state.update(dirty=True,needs_recovery_sync=True,fault='LOCAL_PERSISTENCE_RECONCILIATION_REQUIRED')
                return False
