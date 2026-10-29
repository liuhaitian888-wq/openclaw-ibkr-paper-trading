"""Read-only snapshot Shadow. Local simulation DB only; no broker/SMTP/service owner."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from trading.symbol_health import SymbolRecovery, session_for_symbol


class ShadowRecovery(SymbolRecovery):
    def _event(self,c,symbol,state,resolved=False):
        super()._event(c,symbol,state,resolved)
        # Same transaction: even an accidentally pointed sender cannot claim these.
        c.execute("UPDATE notification_outbox SET status='SHADOW_ONLY' WHERE status='PENDING'")


class ShadowMarketHealth:
    def __init__(self,source_db,output_dir,symbols,*,production_root=None):
        self.source=Path(source_db).resolve(strict=True)
        self.production=Path(production_root or self.source.parent.parent).resolve(strict=True)
        if self.source!=self.production/'runtime/recovery.sqlite3':
            raise ValueError('Source must be the declared production recovery DB')
        self.output=Path(output_dir).resolve()
        if (self.output==self.production or self.production in self.output.parents
                or self.output in self.production.parents or self.output==self.source
                or self.source in self.output.parents or self.output in self.source.parents):
            raise ValueError('Shadow output must be isolated from production and source paths')
        self.output.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name in ('shadow.sqlite3','shadow.sqlite3-wal','shadow.sqlite3-shm','shadow.sqlite3-journal','comparison.jsonl'):
            path=self.output/name
            if (path.resolve().parent!=self.output or path.is_symlink()
                    or (path.exists() and (path.stat().st_nlink>1 or os.path.samefile(path,self.source)))):
                raise ValueError('Unsafe Shadow output alias')
        self.symbols=tuple(symbols);self.now=time.time();self.connection=uuid.uuid4().hex
        mask=os.umask(0o077)
        try:self.policy=ShadowRecovery(self.output/'shadow.sqlite3',self.symbols,clock=lambda:self.now)
        finally:os.umask(mask)
        (self.output/'shadow.sqlite3').chmod(0o600)
        self._new_connection=True

    def step(self,*,now=None):
        self.now=time.time() if now is None else now
        # No schema initialisation or write connection to production; WAL is read consistently.
        with closing(sqlite3.connect(self.source.as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
            c.execute('PRAGMA query_only=ON')
            row=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
            if row is None:raise ValueError('No source snapshot')
            state=json.loads(row[0])
        session=session_for_symbol(self.now)
        simulated=[];health={};diagnoses={}
        for symbol in self.symbols:
            q=dict(state.get('quotes',{}).get(symbol,{}))
            q['data_type']=state.get('market_types',{}).get(symbol,q.get('data_type'))
            error=state.get('market_errors',{}).get(symbol,{})
            if not error and state.get('fault')=='MARKET_DATA_COLLISION':
                # Legacy aggregate evidence is not enough to attribute each symbol.
                error={'scope':'UNKNOWN','reason':'Legacy aggregate collision; no per-symbol evidence'}
            diagnoses[symbol]=dict(error) if error else dict(scope='SYMBOL',reason='Classify current evidence; root cause unconfirmed')
            if state.get('collision_since') is not None and state.get('retries',0)>0:
                self.policy.lifecycle.seed_legacy(symbol,state['retries'],state['collision_since'])
            if error.get('code') is not None:
                fingerprint=json.dumps(error,sort_keys=True)
                with closing(self.policy.store.connect()) as c:prior=self.policy._read(c,'@shadow_error:'+symbol)
                if prior.get('fingerprint')!=fingerprint:
                    self.policy.error(symbol,error['code'],error.get('details',''))
                    with closing(self.policy.store.connect()) as c,c:self.policy._save(c,'@shadow_error:'+symbol,dict(fingerprint=fingerprint))
            q['permission_denied']=error.get('code') in (354,10168,10186)
            if self._new_connection:
                grant=self.policy.lifecycle.reserve(symbol,('quotes','bars','history'),self.connection)
                simulated.append(dict(type='INITIAL_OR_RECONNECT',symbol=symbol,decision=grant))
                if grant['allowed']:
                    self.policy.invalidate_evidence(symbol)
                    self.policy.lifecycle.finish(grant,sent=True,simulated=True)
            result=self.policy.observe(symbol,q,session=session,halted=state.get('market_halts',{}).get(symbol))
            self.policy.verified_recovery(symbol)
            health[symbol]=dict(result['health'],recovery_phase=result['phase'])
            action=self.policy.retry_due(symbol,session=session,connected=bool(state.get('connected') and state.get('identity')))
            if action:
                streams=('bars',) if action['action']=='RESUBSCRIBE_BARS' else ('quotes','bars','history')
                grant=self.policy.lifecycle.reserve(symbol,streams,self.connection,reason=action['action'])
                simulated.append(dict(type='RECOVERY',symbol=symbol,planned_action=action,decision=grant))
                if grant['allowed']:
                    self.policy.invalidate_evidence(symbol)
                    self.policy.lifecycle.finish(grant,sent=True,simulated=True)
        self._new_connection=False
        with closing(self.policy.store.connect()) as c:
            alerts=[dict(id=i,kind=k,incident=key,payload=json.loads(p),delivery='SIMULATED_NEVER_SEND')
                    for i,k,key,p in c.execute('SELECT id,kind,incident_key,payload FROM notification_outbox ORDER BY id')]
        report=dict(mode='SHADOW',observed_at=self.now,session=session,symbol_health=health,diagnoses=diagnoses,
                    old_logic={k:state.get(k) for k in ('fault','retries','retry_at','connected','identity')},
                    would_execute=simulated,simulated_notifications=alerts,
                    source_access='SQLITE_READ_ONLY',production_state_modified=False,
                    broker_requests_sent=0,real_alerts_sent=0,grants_trading_permission=False)
        log=self.output/'comparison.jsonl'
        with log.open('a') as f:f.write(json.dumps(report,sort_keys=True)+'\n')
        log.chmod(0o600)
        return report


def main():
    p=argparse.ArgumentParser(description='Isolated read-only market-health Shadow; no broker connection')
    p.add_argument('--source-db',type=Path,required=True)
    p.add_argument('--production-root',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--symbols',required=True)
    p.add_argument('--samples',type=int,default=1)
    p.add_argument('--interval',type=float,default=5)
    a=p.parse_args()
    if not 1<=a.samples<=10000 or a.interval<1:p.error('Bounded samples1..10000, interval>=1 required')
    runner=ShadowMarketHealth(a.source_db,a.output_dir,tuple(s.strip() for s in a.symbols.split(',') if s.strip()),production_root=a.production_root)
    for i in range(a.samples):
        r=runner.step();print(json.dumps(dict(mode=r['mode'],session=r['session'],states={s:h['status'] for s,h in r['symbol_health'].items()},hypothetical_actions=len(r['would_execute']),broker_requests_sent=0,real_alerts_sent=0)))
        if i+1<a.samples:time.sleep(a.interval)
    return 0

if __name__=='__main__':raise SystemExit(main())
