"""Per-symbol evidence and recovery policy. Never owns broker or SMTP transport."""
from contextlib import closing
import hashlib
import json
import math
import sqlite3
import time
from reporting.incidents import IncidentStore
from trading.subscription_lifecycle import SubscriptionLifecycle, LOW_FREQUENCY_SECONDS

STATES = frozenset(('REALTIME_HEALTHY','REALTIME_STALE','DELAYED','FROZEN',
                    'DELAYED_FROZEN','PERMISSION_DENIED','UNKNOWN'))
ACTIVE = frozenset(('PREMARKET','REGULAR','AFTERHOURS','EARLY_CLOSE'))
CLOSED = frozenset(('CLOSED','WEEKEND','HOLIDAY'))


def session_error_code(code, details):
    """Classify the explicit HMDS competing-session variant, not every 162."""
    text = str(details).lower()
    if code == 162 and ('trading tws session is connected from a different ip address' in text
                        or 'no market data during competing' in text):
        return 10197
    return code


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
        self._adopt_session_errors()

    def _adopt_session_errors(self):
        """Correct legacy classification without erasing evidence or retry budgets."""
        with closing(self.store.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            for symbol in self.symbols:
                key='@retry:'+symbol;s=self._read(c,key)
                if s.get('code')==162 and session_error_code(162,s.get('details',''))==10197:
                    s.update(original_code=162,code=10197,action='RESUBSCRIBE_DATA',
                             classification_corrected_at=self.clock())
                    if s.get('phase')!='NORMAL' and s.get('next_retry') is None:
                        s['next_retry']=self.clock()+30
                    self._save(c,key,s)
                    lifecycle=self.lifecycle.read(c,symbol)
                    self.lifecycle.fault(lifecycle,symbol,'10197')
                    lifecycle['slow_probe_eligible']=True
                    self.lifecycle.save(c,symbol,lifecycle)

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

    def _conflict_notice(self,c,symbol,state,*,resolved=False):
        payload=dict(scope='PAPER_MARKET_SESSION_CONFLICT',symbol=symbol,
            severity='GREEN' if resolved else 'RED',ib_error_code=10197,
            observed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(self.clock())),
            reason='Fresh real-time quotes and complete Paper reconciliation verified' if resolved else 'IBKR reported competing market-data session (10197)',
            action_taken='Observe only; preserve existing orders and all trading gates',
            user_action='None; phone login/logout is not verified' if resolved else 'Check competing session if unintended; phone identity is not verified',
            recovery_condition='Three distinct fresh valid type1 bid/ask observations after conflict, active verified session and fresh complete Paper reconciliation',
            grants_trading_permission=False)
        encoded=json.dumps(payload,sort_keys=True)
        event=f'market-conflict:{symbol}:{state["generation"]}:{resolved}'
        self.store._ingest(c,event,'market-session-conflict:'+symbol,encoded,resolved,self.clock())

    def _observe_conflict(self,c,symbol,fields,health,reconciliation_verified):
        key='@conflict:'+symbol;state=self._read(c,key)
        if not state.get('active'):return
        valid=(reconciliation_verified is True and health['allows_realtime']
               and all(fields.get(k,0)>state['fault_at'] for k in ('bid_at','ask_at')))
        fingerprint=json.dumps([fields.get(k) for k in ('bid_at','ask_at','bid','ask')])
        if valid and fingerprint!=state.get('fingerprint'):
            state['validations']=state.get('validations',0)+1
        elif not valid:state['validations']=0
        state['fingerprint']=fingerprint
        if state.get('validations',0)>=self.validations:
            self._conflict_notice(c,symbol,state,resolved=True);state.update(active=False,recovered_at=self.clock())
        self._save(c,key,state)

    def observe(self,symbol,fields,*,session='UNKNOWN',halted=None,reconciliation_verified=False):
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
            self._observe_conflict(c,symbol,fields,health,reconciliation_verified)
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
        code=session_error_code(code,details)
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
            if code==10197:
                conflict_key='@conflict:'+symbol;conflict=self._read(c,conflict_key)
                if not conflict.get('active'):
                    conflict=dict(active=True,generation=conflict.get('generation',0)+1,fault_at=now,validations=0)
                    self._conflict_notice(c,symbol,conflict)
                else:
                    conflict.update(validations=0,fault_at=now)
                self._save(c,conflict_key,conflict)
            link=self._read(c,'@link:'+symbol)
            if code==1100 and link.get('state')!='LOST':
                link=dict(state='LOST',generation=link.get('generation',0)+1)
            elif code in (1101,1102) and link.get('state')=='LOST':
                link['state']='RESTORED'
                self._save(c,'@condition:'+symbol,dict(key=f'upstream:{link["generation"]}',observed_at=now))
            self._save(c,'@link:'+symbol,link)
            # A secondary HMDS diagnostic must not silence an active quote
            # collision's bounded recovery. Preserve both pieces of evidence.
            if code in (162,321) and s.get('code')==10197 and s.get('phase')!='NORMAL':
                s['secondary_error']=dict(code=code,details=str(details),observed_at=now)
                self._save(c,key,s)
                return s
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
        lifecycle=self.lifecycle.snapshot(symbol)
        slow_due=lifecycle.get('low_frequency_not_before',lifecycle.get('exhausted_at',now)+LOW_FREQUENCY_SECONDS)
        # A slow diagnostic probe is distinct from rearming the fast budget.
        # Session UNKNOWN permits observation, never a recovery declaration.
        if (connected and session in ACTIVE|{'UNKNOWN','SESSION_UNKNOWN'}
                and action in ('RESUBSCRIBE_DATA','RECONCILE_ONLY')
                and (lifecycle.get('slow_probe_eligible') or lifecycle.get('cause')=='10197') and lifecycle.get('attempts',0)>=self.max_attempts
                and not lifecycle.get('pending') and now>=slow_due):
            return dict(action='RESUBSCRIBE_DATA',symbols=[symbol],low_frequency=True,attempt=lifecycle['attempts'])
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
        return self.lifecycle.validated(symbol,evidence_streams=('quotes',))


def symbol_market_permission(state, now, *, max_age=5):
    """Additional gate only; never grants account or execution permission."""
    h=state.get('health',{})
    try:fresh=0<=now-h['observed_at']<=max_age
    except (KeyError,TypeError):fresh=False
    allowed=(fresh and h.get('status')=='REALTIME_HEALTHY' and h.get('allows_realtime') is True
             and state.get('phase')=='NORMAL' and not state.get('fault_active',True))
    return dict(allowed=bool(allowed),reason='Symbol data verified; global gates still required' if allowed else 'Symbol market evidence unavailable, stale or recovery incomplete')


SYSTEMIC_PAUSE_FACTS = ('identity_verified','broker_connected','control_verified',
                        'global_risk_verified','authoritative_state_verified',
                        'reconciliation_verified','risk_isolatable')
PAUSE_RECOVERY_CONDITIONS = ('Fresh actual type1 bid/ask callbacks',
    'Fresh contiguous completed K-lines', 'Account/order reconciliation verified',
    'Symbol and global risk verified', 'Existing execution identity/ownership/kill gates still apply')


def compute_pause_scopes(health, dependencies, system_safety, *, now, kline_ready=None, symbol_risk=None):
    """Pure projection inside the existing market-health owner; no service control.

    dependencies[strategy][traded_symbol] lists its actual market inputs. No
    environment/session pairing changes the impact graph. All failed feeds still
    means L1/L2 unless a separately evidenced systemic condition is untrusted.
    """
    kline_ready = kline_ready or {}
    symbol_risk = symbol_risk or {}
    systemic = [key for key in SYSTEMIC_PAUSE_FACTS if system_safety.get(key) is not True]
    if system_safety.get('operator_paused') is True:systemic.append('OPERATOR_PAUSED')
    targets = sorted({symbol for rows in dependencies.values() for symbol in rows})
    inputs = sorted(set(health) | {s for rows in dependencies.values() for required in rows.values() for s in required})
    faults = {}; market_faults = {}
    for symbol in inputs:
        h=health.get(symbol,{})
        try:fresh=0 <= now-float(h['observed_at']) <= 5
        except (KeyError,TypeError,ValueError,OverflowError):fresh=False
        reasons=[]
        if not fresh or h.get('status')!='REALTIME_HEALTHY' or h.get('allows_realtime') is not True:
            reasons.append(h.get('reason') or 'Fresh verified symbol market data unavailable')
        if kline_ready.get(symbol) is not True:reasons.append('Fresh contiguous completed K-lines unverified')
        if reasons:market_faults[symbol]=list(reasons)
        if symbol in targets and symbol_risk.get(symbol) is not True:reasons.append('SYMBOL_ORDER_RISK_UNVERIFIED')
        if reasons:faults[symbol]=reasons
    decisions={};records=[]
    for symbol,reasons in sorted(faults.items()):
        affected=[name for name,rows in dependencies.items() if any(symbol in required for required in rows.values())]
        records.append(dict(level='L1',scope='SYMBOL_PAUSED',affected_symbols=[symbol],
            affected_strategies=sorted(affected),reason='; '.join(reasons),
            recovery_conditions=list(PAUSE_RECOVERY_CONDITIONS)))
    for name,rows in sorted(dependencies.items()):
        decisions[name]={};blocked=[];sources=set();shared=False
        for target,required in sorted(rows.items()):
            invalid=not required or target not in required or any(not isinstance(s,str) or not s for s in required)
            bad=sorted(s for s in required if s in market_faults)
            reasons=list(systemic)
            if invalid:reasons.append('STRATEGY_DEPENDENCIES_UNVERIFIED')
            if bad:reasons.append('Affected market inputs: '+','.join(bad))
            if symbol_risk.get(target) is not True:reasons.append('SYMBOL_ORDER_RISK_UNVERIFIED')
            allowed=not reasons
            decisions[name][target]=dict(allowed=allowed,market_allowed=not invalid and not bad,symbol_risk_verified=symbol_risk.get(target) is True,required_symbols=list(required),
                affected_inputs=bad,reason='; '.join(reasons) if reasons else 'Scoped market/account/order/risk evidence verified',
                scope='GLOBAL_NEW_ORDERS_PAUSED' if systemic else 'STRATEGY_PAUSED' if len(required)>1 and not allowed else 'SYMBOL_PAUSED' if not allowed else 'RUNNING')
            if not allowed and not systemic:
                blocked.append(target);sources.update(bad);shared=shared or len(required)>1 or invalid
        if blocked and (shared or len(blocked)>1):
            records.append(dict(level='L2',scope='STRATEGY_PAUSED' if len(blocked)==len(rows) else 'MULTI_SYMBOL_PAUSED',
                affected_symbols=sorted(blocked),affected_strategies=[name],source_symbols=sorted(sources),
                reason='Dependency/risk isolation for affected trades; healthy independent trades continue',
                recovery_conditions=list(PAUSE_RECOVERY_CONDITIONS)))
    if systemic:
        records.append(dict(level='L3',scope='GLOBAL_NEW_ORDERS_PAUSED',affected_symbols=targets,
            affected_strategies=sorted(dependencies),reason='; '.join(systemic),
            recovery_conditions=['Re-establish '+key for key in systemic]+list(PAUSE_RECOVERY_CONDITIONS)))
    return dict(observed_at=now,global_new_orders_paused=bool(systemic),global_reasons=systemic,
        affected_symbols=sorted({s for r in records for s in r['affected_symbols']}),
        affected_strategies=sorted({s for r in records for s in r['affected_strategies']}),
        pauses=records,decisions=decisions,grants_trading_permission=False,
        maintenance_continues=['monitoring','broker_reconciliation','alerts','market_recovery'],
        existing_protection_action='PRESERVE; no cancel/modify from market pause')
