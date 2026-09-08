"""Timer/network events request reevaluation, never grant Trading permissions."""
def recover(delivery,manifest,now,approved_hash):
    # Reuses the same hash, ledger, UNKNOWN, retry and preflight checks.
    return delivery.attempt(manifest,now,approved_hash=approved_hash,trigger='recovery')

def trading_recovery_plan(health):
    required=('ibkr.endpoint','ibkr.session','ibkr.account_callback','market.data','data.freshness')
    return {'observations':[health.health(k) for k in required],
            'actions':'Delegate reconnect/resync to existing Trading adapters; no gate mutation',
            'new_risk_authority':'existing Trading-specific safety gates',
            'grants_new_risk':False}

# Shared durable recovery coordinator, using the existing health resolver.
# Callbacks are explicitly read-only/idempotent adapters. It never submits orders
# or invokes delivery.attempt automatically.
import json
import sqlite3
import time
import threading
import fcntl
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
from .health import MODULE_DEPENDENCIES, LIVE_MODULES, resolve_modules

RECOVERY_STEPS=('connect','authenticate','identity','refresh','freshness','reconcile','backlog')
RETRY_POLICY={
 'health':{'idempotent':True,'backoff':2,'max_attempts':None},
 'reconnect':{'idempotent':True,'backoff':5,'max_attempts':None},
 'report':{'idempotent':True,'backoff':10,'max_attempts':3},
 'order':{'idempotent':False,'backoff':None,'max_attempts':1},
 'delivery':{'idempotent':False,'backoff':None,'max_attempts':1},
}

class RecoveryCoordinator:
    """Serial ticks, durable lease/backoff, no new thread or socket ownership."""
    def __init__(self, path, adapters=None, clock=time.time):
        self.path=Path(path);self.adapters=adapters or {};self.clock=clock;self.lock=threading.Lock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as c,c:
            c.executescript('''CREATE TABLE IF NOT EXISTS module_observations(name TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS module_events(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_jobs(name TEXT PRIMARY KEY,owner TEXT,next_retry REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operation_attempts(identity TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL);''')
    def connect(self):return sqlite3.connect(self.path,timeout=.2)
    def observations(self):
        with closing(self.connect()) as c:return {k:json.loads(v) for k,v in c.execute('SELECT name,payload FROM module_observations')}
    def observe(self,name,state,*,freshness='UNKNOWN',reason='',**evidence):
        if name not in MODULE_DEPENDENCIES:raise ValueError('Unknown module')
        now=datetime.fromtimestamp(self.clock(),timezone.utc).isoformat()
        with closing(self.connect()) as c,c:
            old=c.execute('SELECT payload FROM module_observations WHERE name=?',(name,)).fetchone();old=json.loads(old[0]) if old else {}
            value={**old,**evidence,'state':state,'freshness':freshness,'reason':reason,'observed_at':now}
            if state=='HEALTHY':value['last_success']=now
            elif state in ('OFFLINE','FAILED'):value['last_failure']=now
            c.execute('INSERT OR REPLACE INTO module_observations VALUES (?,?)',(name,json.dumps(value,sort_keys=True)))
            if any(old.get(k)!=value.get(k) for k in ('state','freshness','reason')):
                c.execute('INSERT INTO module_events(payload) VALUES (?)',(json.dumps({'module':name,**value}),))
            if name in LIVE_MODULES and (state in ('OFFLINE','FAILED','DEGRADED') or freshness=='STALE'):
                affected={name}
                for child,deps in MODULE_DEPENDENCIES.items():
                    if child in LIVE_MODULES and affected.intersection(deps):
                        affected.add(child)
                        prior=c.execute('SELECT payload FROM module_observations WHERE name=?',(child,)).fetchone()
                        data=json.loads(prior[0]) if prior else {}
                        data.update(state='DEGRADED',freshness='STALE',reason='Invalidated by '+name,
                                    observed_at=now,last_failure=now,recovery_state='WAITING_REFRESH')
                        c.execute('INSERT OR REPLACE INTO module_observations VALUES (?,?)',(child,json.dumps(data,sort_keys=True)))
                        c.execute('INSERT INTO module_events(payload) VALUES (?)',(json.dumps({'module':child,**data}),))
    def snapshot(self):return resolve_modules(self.observations(),now=datetime.fromtimestamp(self.clock(),timezone.utc))
    def begin_operation(self,identity,kind,payload):
        if kind not in ('order','delivery'):raise ValueError('Unknown side effect')
        # Commit BEFORE the caller is permitted to invoke transport. Unique across restarts.
        with closing(self.connect()) as c,c:
            try:c.execute('INSERT INTO operation_attempts VALUES (?,?,?,?)',(identity,kind,'STARTED',json.dumps(payload,sort_keys=True)))
            except sqlite3.IntegrityError:return False
        return True
    def finish_operation(self,identity,status):
        if status not in ('SENT_ACCEPTED','CONFIRMED','UNKNOWN','FAILED_FINAL','SAFE_TO_RETRY'):raise ValueError('Invalid outcome')
        # SAFE_TO_RETRY still needs a new explicitly approved attempt, never delete old identity.
        with closing(self.connect()) as c,c:c.execute('UPDATE operation_attempts SET status=? WHERE identity=?',(status,identity))
    def uncertainties(self):
        with closing(self.connect()) as c:return c.execute("SELECT identity,kind,status FROM operation_attempts WHERE status IN ('STARTED','UNKNOWN')").fetchall()
    def tick(self):
        if not self.lock.acquire(False):return []
        attempted=[]
        lease=None
        try:
            lease=self.path.with_suffix('.recovery.lock').open('a+')
            try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return []
            for module in MODULE_DEPENDENCIES:
                adapter=self.adapters.get(module)
                if adapter is None:continue
                state=self.snapshot()
                if state[module]['state'] in ('HEALTHY','PAUSED'):continue
                if any(state[d]['state']!='HEALTHY' for d in MODULE_DEPENDENCIES[module]):continue
                now=self.clock()
                with closing(self.connect()) as c,c:
                    c.execute('BEGIN IMMEDIATE')
                    row=c.execute('SELECT state,next_retry,attempts FROM recovery_jobs WHERE name=?',(module,)).fetchone()
                    # A crash during recovery requires explicit adapter readback, not duplicate workers.
                    if row and row[0]!='RUNNING' and row[1]>now:continue
                    attempts=(row[2] if row else 0)+1
                    c.execute('INSERT OR REPLACE INTO recovery_jobs VALUES (?,?,?,?,?)',(module,'serial-coordinator',now+min(300,5*2**min(attempts,6)),attempts,'RUNNING'))
                attempted.append(module);self.observe(module,'RECOVERING',reason='Dependency-ordered recovery',recovery_state='connect',next_retry=datetime.fromtimestamp(now+min(300,5*2**min(attempts,6)),timezone.utc).isoformat())
                try:
                    if row and row[0]=='RUNNING' and adapter('reconcile') is not True:
                        raise RuntimeError('Interrupted recovery requires readback')
                    for step in RECOVERY_STEPS:
                        current=self.snapshot()
                        if any(current[d]['state']!='HEALTHY' for d in MODULE_DEPENDENCIES[module]):raise RuntimeError('Dependency changed during recovery')
                        self.observe(module,'RECOVERING',reason=step,recovery_state=step)
                        if adapter(step) is not True:raise RuntimeError('Recovery proof missing: '+step)
                    self.observe(module,'HEALTHY',freshness='FRESH',reason='All recovery checks completed',recovery_state='COMPLETE',next_retry=None)
                    outcome='COMPLETE'
                except Exception as exc:
                    self.observe(module,'DEGRADED',freshness='STALE',reason=str(exc),recovery_state='WAITING_RETRY');outcome='WAITING_RETRY'
                with closing(self.connect()) as c,c:c.execute('UPDATE recovery_jobs SET state=? WHERE name=?',(outcome,module))
            return attempted
        finally:
            if lease:lease.close()
            self.lock.release()
    def reconcile_interrupted_recovery(self,module,*,worker_absent,readback_complete):
        if not worker_absent or not readback_complete:return False
        with closing(self.connect()) as c,c:c.execute("UPDATE recovery_jobs SET state='WAITING_RETRY' WHERE name=? AND state='RUNNING'",(module,))
        return True


def observe_mode9_cycle(coordinator, payload):
    """Adapter for existing Mode 9 results; never upgrades cached account data."""
    account=payload.get('account_state_manager',{})
    verified=(account.get('account_execution_ready') is True and account.get('state_stale') is False
              and account.get('used_cached_state') is False and account.get('force_refresh_ok') is True)
    coordinator.observe('ACCOUNT','HEALTHY' if verified else 'DEGRADED',
        freshness='FRESH' if verified else 'STALE',reason=account.get('blocked_reason') or 'Mode9 account readiness',
        account=account.get('account_id'),environment=account.get('environment'))
    symbols=payload.get('streaming_symbols',[])
    quotes_ok=bool(symbols) and payload.get('streaming_quote_count',0)>=len(symbols) and not payload.get('streaming_stale_symbols') and not payload.get('streaming_errors')
    coordinator.observe('MARKET_DATA','HEALTHY' if quotes_ok else 'DEGRADED',
        freshness='FRESH' if quotes_ok else 'STALE',reason='Mode9 streaming coverage/freshness')
    coordinator.observe('REPORT_ARCHIVE','HEALTHY',reason='Cycle result persisted locally')
    # Strategy readiness is still dependent on canonical/risk/identity observations.
    coordinator.observe('STRATEGY','HEALTHY' if payload.get('ready_for_orders') else 'WAITING_DEPENDENCY',
        freshness='FRESH' if payload.get('ready_for_orders') else 'UNKNOWN',reason='Existing Mode9 execution readiness')
