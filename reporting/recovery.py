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
from .health import MODULE_DEPENDENCIES, LIVE_MODULES, resolve_modules, dependency_registry, callback_owned_modules

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
            if state in ('OFFLINE','FAILED','DEGRADED') or (name in LIVE_MODULES and freshness=='STALE'):
                affected={name}
                observations={k:json.loads(v) for k,v in c.execute('SELECT name,payload FROM module_observations')}
                for child,deps in dependency_registry(observations).items():
                    if affected.intersection(deps):
                        affected.add(child)
                        prior=c.execute('SELECT payload FROM module_observations WHERE name=?',(child,)).fetchone()
                        data=json.loads(prior[0]) if prior else {}
                        previous_phase={k:data.get(k) for k in ('state','freshness','reason','recovery_state')}
                        data.update(state='DEGRADED',freshness='STALE',reason='Invalidated by '+name,
                                    observed_at=now,last_failure=now,recovery_state='WAITING_REFRESH')
                        c.execute('INSERT OR REPLACE INTO module_observations VALUES (?,?)',(child,json.dumps(data,sort_keys=True)))
                        # The parent occurrence is retained above. An unrecovered
                        # child is still in the same loss phase: refresh its local
                        # observation without archiving the same payload again.
                        if any(previous_phase[k]!=data.get(k) for k in previous_phase):
                            c.execute('INSERT INTO module_events(payload) VALUES (?)',(json.dumps({'module':child,**data}),))
    def configure_delivery_transport(self,transport):
        if transport not in ('telegram','smtp','feishu'):raise ValueError('Unknown primary delivery transport')
        with closing(self.connect()) as c,c:
            row=c.execute("SELECT payload FROM module_observations WHERE name='DELIVERY'").fetchone()
            data=json.loads(row[0]) if row else dict(state='DEGRADED',freshness='UNKNOWN',reason='No verified delivery observation')
            data.update(delivery_transport=transport,route_configured_at=datetime.fromtimestamp(self.clock(),timezone.utc).isoformat())
            c.execute("INSERT OR REPLACE INTO module_observations VALUES ('DELIVERY',?)",(json.dumps(data,sort_keys=True),))

    def snapshot(self):return resolve_modules(self.observations(),now=datetime.fromtimestamp(self.clock(),timezone.utc))
    def begin_operation(self,identity,kind,payload):
        if kind not in ('order','delivery'):raise ValueError('Unknown side effect')
        # Commit BEFORE the caller is permitted to invoke transport. Unique across restarts.
        with closing(self.connect()) as c,c:
            # Serialize check-and-reserve across processes, not just one intent key.
            # An ACK lost for A must not be bypassed by generating a new key B.
            c.execute('BEGIN IMMEDIATE')
            if kind=='order' and c.execute("SELECT 1 FROM operation_attempts WHERE kind='order' AND status IN ('STARTED','UNKNOWN') LIMIT 1").fetchone():
                return False
            try:c.execute('INSERT INTO operation_attempts VALUES (?,?,?,?)',(identity,kind,'STARTED',json.dumps(payload,sort_keys=True)))
            except sqlite3.IntegrityError:return False
        return True
    def finish_operation(self,identity,status):
        if status not in ('SENT_ACCEPTED','CONFIRMED','UNKNOWN','FAILED_FINAL','SAFE_TO_RETRY'):raise ValueError('Invalid outcome')
        # SAFE_TO_RETRY still needs a new explicitly approved attempt, never delete old identity.
        with closing(self.connect()) as c,c:c.execute('UPDATE operation_attempts SET status=? WHERE identity=?',(status,identity))
    def uncertainties(self,kind=None):
        sql="SELECT identity,kind,status FROM operation_attempts WHERE status IN ('STARTED','UNKNOWN')"
        with closing(self.connect()) as c:
            return c.execute(sql+(" AND kind=?" if kind is not None else ""),() if kind is None else (kind,)).fetchall()
    def tick(self):
        if not self.lock.acquire(False):return []
        attempted=[]
        lease=None
        try:
            lease=self.path.with_suffix('.recovery.lock').open('a+')
            try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return []
            for module in MODULE_DEPENDENCIES:
                if module in callback_owned_modules(self.observations()):continue
                adapter=self.adapters.get(module)
                if adapter is None:continue
                state=self.snapshot()
                if not state[module].get('active',True) or state[module]['state'] in ('HEALTHY','PAUSED'):continue
                if any(state[d]['state']!='HEALTHY' for d in dependency_registry(self.observations())[module]):continue
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
                        if any(current[d]['state']!='HEALTHY' for d in dependency_registry(self.observations())[module]):raise RuntimeError('Dependency changed during recovery')
                        self.observe(module,'RECOVERING',reason=step,recovery_state=step)
                        if adapter(step) is not True:raise RuntimeError('Recovery proof missing: '+step+'; '+str(getattr(adapter,'observation',{}).get('reason','No proof')))
                        if hasattr(adapter,'observation'):
                            with closing(self.connect()) as c,c:c.execute('INSERT INTO module_events(payload) VALUES (?)',(json.dumps({'module':module,'recovery_step':step,**adapter.observation}),))
                    proof=getattr(adapter,'observation',{})
                    evidence=proof.get('evidence',{})
                    self.observe(module,'HEALTHY',freshness='FRESH',reason=proof.get('reason','All recovery checks completed'),
                        recovery_state='COMPLETE',next_retry=None,adapter_evidence=proof,
                        account=evidence.get('account_id'),environment=evidence.get('environment'))
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


def audit_write_probe(path):
    """Durable benign audit observation; never creates a missing production DB."""
    import uuid
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=.2)) as c,c:
        c.execute('INSERT INTO event_store(event_id,timestamp_utc,source_module,event_type,payload_json) VALUES (?,?,?,?,?)',
            ('health-'+uuid.uuid4().hex,datetime.now(timezone.utc).isoformat(),'dependency_adapter','WRITE_PROBE','{"side_effect":false}'))


def wire_live_adapters(coordinator, state_root, code_root, *, expected_account=None, symbols=(), broker_probe=None):
    """Bind every existing module to real observations. No start/send/order action.

    Local recovery revalidates persisted artifacts; it never manufactures a
    missing database, canonical snapshot, manifest, report or credentials.
    """
    import ssl
    import socket
    import subprocess
    import hashlib
    import os
    from .live_observation import probe
    from trading.production_paths import maintenance_active
    root=Path(state_root).resolve();code=Path(code_root).resolve();cache={}
    try:approved=json.loads((root/'production.json').read_text())
    except (OSError,ValueError):approved={}
    expected_account=expected_account or approved.get('account')
    symbols=tuple(symbols or approved.get('market_symbols',()))
    def read(path):return json.loads(Path(path).read_text())
    def broker():
        if coordinator.observations().get('NATIVE_BROKER_SESSION',{}).get('enabled') is True:
            raise PermissionError('Existing native owner reserves broker transport; no independent generic probe')
        host=os.environ.get('TWS_HOST','127.0.0.1')
        port=int(os.environ.get('TWS_PORT','7497'))
        if host!='127.0.0.1' or port not in (4002,7497):
            raise ValueError('Readback requires a loopback Paper endpoint')
        if not cache.get('broker') or time.time()-cache['at']>30:
            cache['broker']=(broker_probe or probe)(host=host,port=port,expected_account=expected_account,symbols=symbols,timeout=8)
            cache['at']=time.time()
        return cache['broker']
    def check(module):
        if module in ('TELEGRAM','SMTP'):
            return False,'Recent native delivery acknowledgement required; quiet channel is not proof of failure or permission to send a test',{}
        if module=='NEWS':
            from trading.news_feed import load_evidence, capability
            evidence=load_evidence(root/'runtime/news.latest.json')
            ok=evidence.get('expected_account')==expected_account and capability(evidence)
            return ok,'Independent broker news retrieval evidence; no replay or subscription',evidence
        if module in ('PROTECTION','PAPER_SESSION'):
            # Only the event-driven monitor may produce these facts. The generic
            # recovery walker cannot upgrade its own cached observations.
            return False,'Fresh callback safety monitor evidence required',{}
        if module=='NETWORK':
            successes=[];failures=[]
            provider=dependency_registry(coordinator.observations())['DELIVERY'][-1]
            endpoint='api.telegram.org' if provider=='TELEGRAM' else 'open.feishu.cn'
            for host in (endpoint,'www.interactivebrokers.com'):
                try:
                    with socket.create_connection((host,443),timeout=4) as sock:
                        with ssl.create_default_context().wrap_socket(sock,server_hostname=host) as tls:successes.append({'host':host,'tls':tls.version()})
                except (OSError,TimeoutError) as exc:failures.append({'host':host,'error':type(exc).__name__})
            return bool(successes),'Fresh verified TLS egress; endpoint health remains separate',{'successes':successes,'failures':failures}
        if module in ('IBKR_CONNECTION','ACCOUNT','POSITIONS','ORDERS','EXECUTIONS','MARKET_DATA'):
            b=broker();ok=b['complete'] and expected_account is not None and b['account_id']==expected_account and b['environment']=='PAPER'
            if module=='MARKET_DATA':ok=ok and bool(symbols) and set(symbols)==set(approved.get('market_symbols',())) and set(b['quotes'])==set(symbols) and all(q.get('data_type')==1 and q.get('bid',0)>0 and q.get('ask',0)>0 and q.get('received_at') for q in b['quotes'].values())
            if module=='ACCOUNT':ok=ok and all(v['value'] is not None and v['currency'] for v in b['account'].values()) and b['pnl'] is not None
            if module in ('POSITIONS','ORDERS','EXECUTIONS'):ok=ok and all(x.get('account')==expected_account for x in b[module.lower()])
            return ok,'Live IBKR end markers/account/market evidence' if ok else 'Missing approved account, complete readback or live quote evidence',b
        if module in ('DATABASE','AUDIT','EVENT_STORE'):
            audit_write_probe(root/'trading_audit.sqlite3')
            return True,'Audit write committed',{'path':str(root/'trading_audit.sqlite3')}
        if module=='LOCAL_STATE':
            with closing(coordinator.connect()) as c,c:c.execute('INSERT INTO module_events(payload) VALUES (?)',('{"local_write_probe":true}',))
            return True,'Local journal write committed',{'path':str(coordinator.path)}
        if module=='DIAGNOSTICS':
            from trading.production_diagnostics import process_snapshot
            evidence=process_snapshot();return evidence.get('open_fd_count') is not None,'Live owner process observation',evidence
        if module=='REPORT_ARCHIVE':
            p=root/'reports';return p.is_dir() and any(p.iterdir()),'Local report archive availability',{'path':str(p)}
        if module=='FINANCIAL_LEDGER':
            p=root/'financial_ledger.sqlite3'
            with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as c:
                accounts={x[0] for x in c.execute('SELECT DISTINCT account FROM observations')}
            return bool(expected_account) and accounts=={expected_account},'Financial observation account scope',{'accounts':sorted(accounts),'path':str(p)}
        if module in ('DELIVERY_LEDGER','DELIVERY') and dependency_registry(coordinator.observations())['DELIVERY'][-1] in ('TELEGRAM','SMTP'):
            with closing(sqlite3.connect(coordinator.path.as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
                counts=dict(c.execute('SELECT status,count(*) FROM notification_outbox GROUP BY status'))
                uncertain=sum(counts.get(s,0) for s in ('STARTED','UNKNOWN'))
                receipts=c.execute('SELECT count(*) FROM notification_receipts').fetchone()[0]
            return (module=='DELIVERY_LEDGER' or uncertain==0),'Shared durable notification outbox readback; no resend',dict(status_counts=counts,uncertain=uncertain,receipts=receipts,path=str(coordinator.path))
        if module=='DELIVERY_LEDGER':
            d=read(root/'delivery.json');records=d.get('reports',{})
            unknown=[k for k,v in records.items() if v.get('status') in ('UNKNOWN','STARTED','SENDING','ACCEPTED_PENDING_COMMIT')]
            return d.get('schema_version')==2 and isinstance(records,dict),'Persistent delivery ledger; uncertainty stays held',{'unknown':unknown,'records':len(records)}
        if module=='FEISHU':
            # Refresh actual app authentication; never use a cached token as proof.
            from scripts.send_feishu_report import load_env_file,tenant_access_token
            load_env_file(code/'.secrets/feishu_webhook.env')
            load_env_file(code/'.secrets/feishu_image_upload.env')
            token=tenant_access_token(force_refresh=True)
            return False,'App authentication refreshed; custom webhook acceptance has no read-only verification API',{'fresh_app_auth':bool(token),'send_attempted':False}
        manifest=read(root/'production.json')
        if module=='MANIFEST':
            commit=subprocess.check_output(['git','-C',str(code),'rev-parse','HEAD'],text=True).strip()
            ok=manifest.get('ready') is True and manifest.get('commit')==commit and manifest.get('state_root')==str(root)
            return ok,'Approved deployment identity',{'commit':commit,'approved':ok}
        if module=='CANONICAL_STATE':
            p=root/'trading_audit.sqlite3'
            with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)) as c:
                duplicates=c.execute('SELECT symbol,count(*) FROM canonical_pool_state GROUP BY symbol HAVING count(*)>1').fetchall()
                count=c.execute('SELECT count(*) FROM canonical_pool_state').fetchone()[0]
            return bool(count) and not duplicates and manifest.get('canonical_current_state_verified') is True,'Canonical projection and approved reconciliation',{'rows':count,'duplicates':duplicates}
        if module=='REPORT':
            report=read(manifest['report_manifest']);artifact=Path(report['artifact_path']);actual=hashlib.sha256(artifact.read_bytes()).hexdigest()
            source=Path(report['source_json']);source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            from scripts.production_health import fresh
            ok=actual==report['artifact_hash'] and source_hash==report['source_hash'] and fresh(report.get('created_at'),seconds=86400) and report.get('simulation') is not True and report.get('validation',{}).get('ready') is True
            return ok,'Current report/source hashes and generation freshness',{'report_id':report['report_id'],'artifact_hash':actual,'created_at':report.get('created_at')}
        if module=='WATCHDOG':
            from scripts.production_health import recent_resource,fresh
            from trading.production_diagnostics import process_inventory
            sample=recent_resource('execution')
            owners=[p for p in process_inventory() if p['pid']==sample.get('pid') and 'run_autonomous_trading_agent.py' in p['command']]
            ok=bool(owners) and fresh(sample.get('timestamp')) and sample.get('fd_status')=='OK' and not maintenance_active(root)
            return ok,'Existing resource monitor live owner/heartbeat; never enables jobs',{'maintenance':maintenance_active(root),'sample':sample,'owners':owners}
        if module=='RISK':
            from trading.order_ownership import classify_order,exposure_snapshot,verified_historical_intents
            b=broker()
            ownership=[classify_order(o,verified_historical_intents(o,manifest.get('ownership_review_paths',[]),account=expected_account,environment=b['environment']),account=expected_account,environment=b['environment'],
                external_evidence=o.get('client_id')==0 and not o.get('order_ref')) for o in b['orders']]
            # A system claim needs published provenance; absence never implies manual.
            ok=b['complete'] and bool(expected_account) and b['account_id']==expected_account and all(x['ownership']!='UNKNOWN' for x in ownership)
            return ok,'Live exposure includes every manual/system order; unresolved ownership blocks risk readiness',{
                'exposure':exposure_snapshot(b['orders'],b['positions']),'ownership':ownership,'account_id':b['account_id'],'environment':b['environment']}
        if module=='STRATEGY':
            cycle=read(root/'reports/autonomous_agent/latest.json')
            age=time.time()-datetime.fromisoformat(cycle['created_at']).timestamp()
            account=cycle.get('account_state_manager',{})
            ok=0<=age<=60 and cycle.get('ready_for_orders') is True and cycle.get('quote_execution_ready') is True and not cycle.get('errors') and account.get('account_id')==expected_account and account.get('used_cached_state') is False and account.get('force_refresh_ok') is True
            return ok,'Existing Mode9 current-cycle account/quote readiness; no strategy execution by adapter',{'created_at':cycle['created_at'],'blocked_reason':cycle.get('blocked_reason'),'account':account}
        if module=='ORDER_SUBMISSION':
            with closing(sqlite3.connect((root/'trading_audit.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
                pending=c.execute("SELECT idempotency_key,status FROM order_requests WHERE status IS NULL OR status NOT IN ('FILLED','CANCELLED','REJECTED','FAILED_FINAL')").fetchall()
                latest=c.execute('SELECT completed_at,status FROM reconciliation_runs ORDER BY completed_at DESC LIMIT 1').fetchone()
            age=time.time()-datetime.fromisoformat(latest[0]).timestamp() if latest else float('inf')
            ok=not pending and not coordinator.uncertainties(kind='order') and latest and latest[1]=='OK' and 0<=age<=60
            return bool(ok),'Existing broker reconciliation must be current; ambiguous attempts remain held',{'pending':pending,'latest_reconciliation':latest}
        if module=='DELIVERY':
            d=read(root/'delivery.json')
            unresolved=[k for k,v in d['reports'].items() if v.get('status') in ('UNKNOWN','STARTED','SENDING','ACCEPTED_PENDING_COMMIT')]
            return not unresolved,'Existing ledger readback; no automatic resend',{'unresolved':unresolved}
        raise ValueError('No production adapter for '+module)
    class Adapter:
        def __init__(self,module):self.module=module;self.observation={}
        def __call__(self,step):
            if step=='connect' or not self.observation:
                if self.module=='IBKR_CONNECTION':cache.clear()
                try:
                    ok,reason,evidence=check(self.module)
                    self.observation={'ok':ok,'reason':reason,'evidence':evidence,'sampled_at':datetime.now(timezone.utc).isoformat()}
                except Exception as exc:self.observation={'ok':False,'reason':type(exc).__name__+': '+str(exc),'evidence':{},'sampled_at':datetime.now(timezone.utc).isoformat()}
            self.observation['step']=step
            if self.module in ('IBKR_CONNECTION','ACCOUNT','POSITIONS','ORDERS','EXECUTIONS','MARKET_DATA'):
                b=self.observation.get('evidence',{})
                phase={
                    'connect':bool(b.get('server_time')),
                    'authenticate':bool(b.get('account_id')) and b.get('environment')=='PAPER',
                    'identity':bool(expected_account) and b.get('account_id')==expected_account,
                    'refresh':b.get('complete') is True,
                    'freshness':bool(b.get('observed_at')) and 0<=time.time()-datetime.fromisoformat(b['observed_at']).timestamp()<60,
                    'reconcile':all(x.get('account')==expected_account for k in ('positions','orders','executions') for x in b.get(k,[])),
                    'backlog':not coordinator.uncertainties(kind='order'), # Broker ambiguity only; delivery remains under DELIVERY.
                }
                self.observation['phase_verified']=phase.get(step,False)
                if step=='backlog':self.observation['uncertainties_retained']=coordinator.uncertainties(kind='order')
                return self.observation['ok'] is True and phase.get(step,False)
            return self.observation['ok'] is True
    coordinator.adapters={name:Adapter(name) for name in MODULE_DEPENDENCIES}
    return coordinator.adapters
