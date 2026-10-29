"""Per-symbol evidence and recovery policy. Never owns broker or SMTP transport."""
from contextlib import closing
import hashlib
import json
import math
import sqlite3
import time
from reporting.incidents import IncidentStore
from trading.subscription_lifecycle import SubscriptionLifecycle

STATES = frozenset(('REALTIME_HEALTHY','REALTIME_STALE','DELAYED','FROZEN',
                    'DELAYED_FROZEN','PERMISSION_DENIED','UNKNOWN'))
ACTIVE = frozenset(('PREMARKET','REGULAR','AFTERHOURS','EARLY_CLOSE'))
CLOSED = frozenset(('CLOSED','WEEKEND','HOLIDAY'))


def classify_symbol(fields, now, *, session='SESSION_UNKNOWN', halted=None, max_age=5):
    """Freshness is callback age, not a claim of exchange-to-client latency."""
    kind = fields.get('data_type')
    status = {2:'FROZEN',3:'DELAYED',4:'DELAYED_FROZEN'}.get(kind,'UNKNOWN')
    reason = 'Actual marketDataType unavailable'
    if fields.get('permission_denied') is True:
        status, reason = 'PERMISSION_DENIED','Explicit request permission rejection'
    elif kind in (2,3,4):
        reason = 'Actual marketDataType=' + str(kind)
    elif kind == 1:
        try:
            bid, ask = float(fields['bid']), float(fields['ask'])
            ages = [now-float(fields[k]) for k in ('bid_at','ask_at')]
            fresh = (all(math.isfinite(x) for x in [bid,ask,*ages]) and 0<bid<=ask
                     and all(0<=age<=max_age for age in ages))
            status = 'REALTIME_HEALTHY' if fresh else 'REALTIME_STALE'
            reason = 'Type1 and fresh uncrossed callbacks' if fresh else 'Bid/ask invalid or callback age outside limit'
        except (KeyError,TypeError,ValueError,OverflowError):
            status,reason = 'REALTIME_STALE','Type1 but complete valid bid/ask evidence missing'
    halted_known = halted in (1,2)
    permitted = status=='REALTIME_HEALTHY' and session in ACTIVE and not halted_known
    if halted_known:reason='Broker Halted49=' + str(halted)
    elif session not in ACTIVE:reason += '; session=' + session
    return dict(status=status, reason=reason, session=session, halted=halted,
                allows_realtime=permitted, timestamp_quality='RECEIVE_ONLY',
                exchange_latency_verified=False, observed_at=now,
                low_liquidity='UNCONFIRMED', halt_clearance='UNKNOWN' if halted is None or halted==-1 else 'BROKER_REPORTED')


def session_for_symbol(now, *, contract_details=None):
    """Reuse existing calendar. Missing verified schedule is UNKNOWN, never weekday inference."""
    from datetime import datetime, timezone
    from trading.market_session import current_market_session, MarketSessionConfig
    try:
        snap=current_market_session(now=datetime.fromtimestamp(now,timezone.utc),
                                    symbols=tuple((contract_details or {}).keys()),
                                    config=MarketSessionConfig(require_verified_calendar=True),
                                    contract_details=contract_details)
    except (OSError,ValueError,TypeError,KeyError,OverflowError):
        return 'SESSION_UNKNOWN'
    # A local-file miss is not an authoritative schedule for this date.
    if snap.calendar_source_confidence!='high':return 'SESSION_UNKNOWN'
    if any(row.get('calendar_contract_conflict') for row in snap.symbols):return 'SESSION_UNKNOWN'
    return 'SESSION_UNKNOWN' if snap.session_state=='UNKNOWN' else snap.session_state


class SymbolRecovery:
    """Durable max-four budget per incident. Repeated errors never replenish it."""
    def __init__(self, path, symbols, *, clock=time.time, max_attempts=4,
                 cooldown=300, notify_after=60, validations=3):
        if max_attempts<1 or cooldown<0 or notify_after<0 or validations<1:
            raise ValueError('Positive recovery budget and validation count required')
        self.store=IncidentStore(path);self.clock=clock
        self.lifecycle=SubscriptionLifecycle(path,clock=clock,max_attempts=max_attempts,cooldown=cooldown)
        self.symbols=tuple(dict.fromkeys(symbols))
        self.max_attempts,self.cooldown,self.notify_after,self.validations=max_attempts,cooldown,notify_after,validations
        with closing(self.store.connect()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS symbol_health_runtime (key TEXT PRIMARY KEY,payload TEXT NOT NULL)')

    @staticmethod
    def _read(c,key):
        row=c.execute('SELECT payload FROM symbol_health_runtime WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else {}

    @staticmethod
    def _save(c,key,state):
        c.execute('INSERT OR REPLACE INTO symbol_health_runtime VALUES (?,?)',(key,json.dumps(state,sort_keys=True)))

    def snapshot(self,symbol):
        with closing(self.store.connect()) as c:return self._read(c,symbol)

    def _event(self,c,symbol,state,resolved=False):
        payload=dict(scope='SYMBOL_MARKET_DATA',symbol=symbol,reason=state['health']['reason'],
                     market_data_status=state['health']['status'],
                     severity='GREEN' if resolved else ('RED' if state['health']['status']=='PERMISSION_DENIED' or state['health']['halted'] in (1,2) else 'YELLOW'),recovery_state=state['phase'],
                     action_taken='Block affected symbol new strategy orders; preserve protective orders',
                     user_action='None' if resolved else 'Review affected feed/session/permission evidence',
                     source='CLOUD_API',grants_trading_permission=False)
        encoded=json.dumps(payload,sort_keys=True)
        event=hashlib.sha256((symbol+str(state['episode'])+encoded+str(resolved)).encode()).hexdigest()
        self.store._ingest(c,event,'symbol-market-data:'+symbol,encoded,resolved,self.clock())

    def observe(self,symbol,fields,*,session='UNKNOWN',halted=None):
        if symbol not in self.symbols:raise ValueError('Symbol outside preserved universe')
        now=self.clock();health=classify_symbol(fields,now,session=session,halted=halted)
        fingerprint=json.dumps([fields.get(k) for k in ('data_type','bid_at','ask_at','bid','ask')])
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self._read(c,symbol)
            s.setdefault('episode',0);s.setdefault('phase','NORMAL');s.setdefault('attempts',0);s.setdefault('fault_active',False)
            previous_session=s.get('health',{}).get('session')
            if ((previous_session in CLOSED and session in ACTIVE)
                    or (previous_session=='PREMARKET' and session in ('REGULAR','EARLY_CLOSE'))):
                s['since']=now
                self._save(c,'@condition:'+symbol,dict(key=f'session:{session}:{int(now//86400)}',observed_at=now))
            s['health']=health
            s['evidence']={k:fields.get(k) for k in ('con_id','exchange','sec_type','currency','request_id','requested_type','data_type','bid','ask','last','bid_at','ask_at','last_at','event_time')}
            if health['allows_realtime']:s['last_success_at']=now
            if health['allows_realtime']:
                if s.get('fingerprint')!=fingerprint:
                    s['validations']=s.get('validations',0)+1
                s['phase']='VALIDATING' if s.get('fault_active') else 'NORMAL'
                if s.get('validations',0)>=self.validations and s.get('fault_active'):
                    s.update(phase='NORMAL',fault_active=False,attempts=0,next_retry=None)
                    self._event(c,symbol,s,resolved=True)
            else:
                s['validations']=0
                if not s.get('fault_active'):
                    s.update(episode=s['episode']+1,fault_active=True,since=now,phase='SUSPECT',attempts=0)
                if session in CLOSED and halted not in (1,2):
                    s['phase']='MARKET_CLOSED'
                elif now-s.get('since',now)>=self.notify_after or halted in (1,2) or health['status']=='PERMISSION_DENIED':
                    s['phase']='BLOCKED';self._event(c,symbol,s)
            s['fingerprint']=fingerprint;self._save(c,symbol,s)
            return s

    def invalidate_evidence(self,symbol):
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self._read(c,symbol)
            s.setdefault('episode',0)
            if not s.get('fault_active'):s['episode']+=1
            s.update(validations=0,fingerprint=None,fault_active=True,phase='VALIDATING',since=self.clock())
            self._save(c,symbol,s)

    def error(self,symbol,code,details,*,confirmed_shared=False):
        if symbol not in self.symbols:raise ValueError('Unknown symbol')
        now=self.clock()
        affected=self.symbols if confirmed_shared and code==10197 else (symbol,)
        if code in (10197,1100,1101,10225):
            for target in affected:
                self.lifecycle.open_fault(target,str(code))
                self.invalidate_evidence(target)
        # Scope expansion needs explicit caller evidence, never the code alone.
        key='@shared_session' if confirmed_shared and code==10197 else '@retry:'+symbol
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');s=self._read(c,key)
            link=self._read(c,'@link:'+symbol)
            if code==1100 and link.get('state')!='LOST':
                link=dict(state='LOST',generation=link.get('generation',0)+1)
            elif code in (1101,1102) and link.get('state')=='LOST':
                link['state']='RESTORED'
                self._save(c,'@condition:'+symbol,dict(key=f'upstream:{link["generation"]}',observed_at=now))
            self._save(c,'@link:'+symbol,link)
            if not s or s.get('phase')=='NORMAL':
                s=dict(attempts=0,next_retry=now+30,phase='BLOCKED',episode=s.get('episode',0)+1)
            s.update(code=code,details=str(details),affected=list(self.symbols) if key=='@shared_session' else [symbol])
            s['action']='RESUBSCRIBE_DATA'
            if code==10225:s.update(action='RESUBSCRIBE_BARS',next_retry=now if s['attempts']==0 else s['next_retry'])
            elif code==1101:s['next_retry']=now if s['attempts']==0 else s['next_retry']
            elif code==1102:s.update(action='RECONCILE_ONLY',next_retry=None)
            elif code==1100:s.update(action='WAIT_CONNECTION',next_retry=None)
            elif code in (101,354,10168,10186):s.update(action='HUMAN_REVIEW',next_retry=None)
            elif code in (162,321):s.update(action='DIAGNOSE_MESSAGE',next_retry=None)
            self._save(c,key,s)
            return s

    def retry_due(self,symbol,*,session='UNKNOWN',connected=False):
        now=self.clock()
        with closing(self.store.connect()) as c:
            condition=self._read(c,'@condition:'+symbol);local_retry=self._read(c,'@retry:'+symbol)
        # 1102 alone preserves streams. A later verified session boundary is an
        # independent condition; it may rearm an exhausted legacy episode even
        # when an earlier 1102 left the retry policy at RECONCILE_ONLY.
        action=local_retry.get('action','RESUBSCRIBE_DATA')
        session_change=condition.get('key','').startswith('session:')
        eligible=action in ('RESUBSCRIBE_DATA','RESUBSCRIBE_BARS') or (session_change and action=='RECONCILE_ONLY')
        rearmed=bool(connected and session in ACTIVE and condition and eligible and
                     self.lifecycle.rearm(symbol,condition['key'],condition['observed_at']))
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            shared=self._read(c,'@shared_session');key='@shared_session' if shared and shared.get('phase')!='NORMAL' else '@retry:'+symbol
            s=self._read(c,key)
            if rearmed:
                if not s:s=dict(episode=1,affected=[symbol],action='RESUBSCRIBE_DATA')
                s.update(attempts=0,next_retry=now,phase='BLOCKED',rearm_condition=condition['key'])
                if s.get('action')=='RECONCILE_ONLY':s['action']='RESUBSCRIBE_DATA'
            if (not connected or session not in ACTIVE|{'UNKNOWN','SESSION_UNKNOWN'} or not s or s.get('next_retry') is None
                    or now<s['next_retry'] or s['attempts']>=self.max_attempts):return None
            s['attempts']+=1;s['phase']='RECOVERING'
            if s['attempts']>=self.max_attempts:s.update(phase='COOLDOWN',next_retry=None,cooldown_until=now+self.cooldown)
            else:s['next_retry']=now+(30,60,120,300)[s['attempts']]
            targets=[x for x in s['affected'] if not (self._read(c,x).get('phase')=='NORMAL' and self._read(c,x).get('health',{}).get('allows_realtime'))
                and self._read(c,'@retry:'+x).get('action')!='HUMAN_REVIEW']
            self._save(c,key,s)
            return dict(action=s['action'],symbols=targets,attempt=s['attempts'],episode=s['episode']) if targets else None

    def verified_recovery(self,symbol):
        """Explicit, evidence-backed reset; never changes a trading/global switch."""
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');state=self._read(c,symbol)
            if state.get('phase')!='NORMAL' or state.get('validations',0)<self.validations or not state.get('health',{}).get('allows_realtime'):
                return False
            key='@retry:'+symbol;s=self._read(c,key)
            if s:s.update(phase='NORMAL',next_retry=None);self._save(c,key,s)
            shared=self._read(c,'@shared_session')
            if shared and all(self._read(c,x).get('phase')=='NORMAL' and self._read(c,x).get('validations',0)>=self.validations for x in shared['affected']):
                shared.update(phase='NORMAL',next_retry=None);self._save(c,'@shared_session',shared)
        return self.lifecycle.validated(symbol)


def symbol_market_permission(state, now, *, max_age=5):
    """Additional gate only; never grants account or execution permission."""
    h=state.get('health',{})
    try:fresh=0<=now-h['observed_at']<=max_age
    except (KeyError,TypeError):fresh=False
    allowed=(fresh and h.get('status')=='REALTIME_HEALTHY' and h.get('allows_realtime') is True
             and state.get('phase')=='NORMAL' and not state.get('fault_active',True))
    return dict(allowed=bool(allowed),reason='Symbol data verified; global gates still required' if allowed else 'Symbol market evidence unavailable, stale or recovery incomplete')
