"""Durable subscription admission. No sockets, orders, SMTP or service control."""
from contextlib import closing
import json
import sqlite3
import time
import uuid

LOW_FREQUENCY_SECONDS = 900

STREAMS=frozenset(('quotes','bars','history'))

class SubscriptionLifecycle:
    def __init__(self,path,*,clock=time.time,max_attempts=4,cooldown=300):
        if max_attempts<1:raise ValueError('Positive recovery budget required')
        if cooldown<0:raise ValueError('Nonnegative cooldown required')
        self.path=str(path);self.clock=clock;self.max_attempts=max_attempts;self.cooldown=cooldown
        with closing(self.connect()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS subscription_lifecycle(symbol TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS subscription_requests(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,incident TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL)')
    def connect(self):return sqlite3.connect(self.path,timeout=2)
    @staticmethod
    def read(c,symbol):
        row=c.execute('SELECT payload FROM subscription_lifecycle WHERE symbol=?',(symbol,)).fetchone()
        return json.loads(row[0]) if row else dict(seen=[],attempts=0,serial=0,incident=None,connections={})
    @staticmethod
    def save(c,symbol,s):c.execute('INSERT OR REPLACE INTO subscription_lifecycle VALUES (?,?)',(symbol,json.dumps(s,sort_keys=True)))
    def snapshot(self,symbol):
        with closing(self.connect()) as c:return self.read(c,symbol)
    @staticmethod
    def fault(s,symbol,cause):
        if s.get('incident') is None:
            s['serial']+=1;s.update(incident=f'{symbol}:{s["serial"]}',attempts=0,cause=cause)
    def open_fault(self,symbol,cause):
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self.read(c,symbol);self.fault(s,symbol,cause)
            if cause=='10197':s['slow_probe_eligible']=True
            self.save(c,symbol,s)
    def seed_legacy(self,symbol,attempts,incident):
        """One-time adoption: deployment cannot replenish an already used budget."""
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM subscription_lifecycle WHERE symbol=?',(symbol,)).fetchone():return
            s=self.read(c,symbol);self.fault(s,symbol,'LEGACY_INCIDENT')
            s.update(seen=sorted(STREAMS),attempts=min(max(0,int(attempts)),self.max_attempts),legacy_incident=str(incident))
            if s['attempts']>=self.max_attempts:s.update(exhausted_at=self.clock(),cooldown_until=self.clock()+self.cooldown)
            self.save(c,symbol,s)
    def reserve(self,symbol,streams,connection,*,reason='INITIAL'):
        streams=tuple(sorted(set(streams)))
        if not symbol or not connection or not streams or set(streams)-STREAMS:raise ValueError('Explicit symbol, stream and connection identity required')
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self.read(c,symbol)
            if s.get('pending'):return dict(allowed=False,reason='PENDING_OR_UNKNOWN_REQUEST')
            if reason=='INITIAL' and all(s['connections'].get(k)==connection for k in streams):
                return dict(allowed=False,reason='DUPLICATE_INITIAL_SUBSCRIPTION')
            initial=not s['seen'] and s.get('incident') is None and reason=='INITIAL'
            if not initial:
                self.fault(s,symbol,'RECONNECT' if reason=='INITIAL' else reason)
                if s['attempts']>=self.max_attempts:
                    if reason!='LOW_FREQUENCY_RECOVERY' or not (s.get('slow_probe_eligible') or s.get('cause')=='10197'):
                        return dict(allowed=False,reason='INCIDENT_BUDGET_EXHAUSTED',incident=s['incident'],attempt=s['attempts'])
                    due=s.get('low_frequency_not_before',s.get('exhausted_at',self.clock())+LOW_FREQUENCY_SECONDS)
                    if self.clock()<due:return dict(allowed=False,reason='LOW_FREQUENCY_BACKOFF',not_before=due)
                    # Reserve durably before dispatch; restart and concurrent owners
                    # cannot spend another slow probe or replenish fast attempts.
                    s['low_frequency_not_before']=self.clock()+LOW_FREQUENCY_SECONDS
                    s['low_frequency_attempts']=s.get('low_frequency_attempts',0)+1
                elif reason=='LOW_FREQUENCY_RECOVERY':
                    return dict(allowed=False,reason='FAST_BUDGET_NOT_EXHAUSTED')
                if self.clock()<s.get('not_before',0):return dict(allowed=False,reason='INCIDENT_BACKOFF',incident=s['incident'])
                if reason!='LOW_FREQUENCY_RECOVERY':s['attempts']+=1
                s['not_before']=self.clock()+(30,60,120,300)[min(s['attempts']-1,3)]
                if s['attempts']>=self.max_attempts and reason!='LOW_FREQUENCY_RECOVERY':s.update(exhausted_at=self.clock(),cooldown_until=self.clock()+self.cooldown)
            request_id=uuid.uuid4().hex
            incident=s.get('incident') or f'{symbol}:bootstrap'
            grant=dict(allowed=True,id=request_id,symbol=symbol,streams=streams,connection=connection,
                       incident=incident,attempt=s['attempts'],reason=reason,initial=initial,
                       replaces=tuple(k for k in streams if s['connections'].get(k)==connection),observed_at=self.clock())
            s['pending']=request_id;s['seen']=sorted(set(s['seen'])|set(streams))
            for stream in streams:s['connections'][stream]=connection
            self.save(c,symbol,s)
            c.execute('INSERT INTO subscription_requests VALUES (?,?,?,?,?)',(request_id,symbol,incident,json.dumps(grant,sort_keys=True),'RESERVED'))
            return grant
    def finish(self,grant,*,sent,simulated=False):
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self.read(c,grant['symbol'])
            row=c.execute('SELECT status FROM subscription_requests WHERE id=?',(grant['id'],)).fetchone()
            if not row or row[0]!='RESERVED' or s.get('pending')!=grant['id']:raise ValueError('Request ownership mismatch')
            c.execute('UPDATE subscription_requests SET status=? WHERE id=?',('SIMULATED' if sent and simulated else 'DISPATCHED_UNCONFIRMED' if sent else 'UNKNOWN',grant['id']))
            if sent:s.pop('pending',None)
            # Unknown or process death remains held; never auto-replayed.
            self.save(c,grant['symbol'],s)
    def validated(self,symbol,*,evidence_streams=None):
        """Caller must first prove distinct fresh observations via SymbolRecovery."""
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self.read(c,symbol)
            if s.get('pending'):return False
            if s.get('incident') and evidence_streams is not None:
                proof=set(evidence_streams)
                required='history' if s.get('cause') in ('HISTORY_GAP','HISTORY_RECOVERY') else 'bars' if s.get('cause')=='10225' else 'quotes'
                if required not in proof:return False
            s.update(incident=None,attempts=0,not_before=0)
            s.pop('low_frequency_not_before',None)
            s.pop('slow_probe_eligible',None)
            self.save(c,symbol,s);return True

    def rearm(self,symbol,condition,observed_at):
        """Cooldown alone never replenishes budget; a later condition must change."""
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self.read(c,symbol)
            if (s.get('pending') or s['attempts']<self.max_attempts or not condition
                    or self.clock()<s.get('cooldown_until',float('inf'))
                    or observed_at<=s.get('exhausted_at',float('inf'))
                    or observed_at>self.clock() or condition in s.get('rearmed_conditions',[])):
                return False
            prior=s.get('incident');s['serial']+=1
            s.update(incident=f'{symbol}:{s["serial"]}',attempts=0,not_before=0,
                     rearmed_conditions=(s.get('rearmed_conditions',[])+[condition])[-32:],
                     rearmed_from=prior,rearm_condition=condition,rearmed_at=self.clock())
            self.save(c,symbol,s);return True
