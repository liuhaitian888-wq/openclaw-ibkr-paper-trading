"""Read-only Paper safety evidence. No broker mutation or SMTP transport."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from trading.audit import AuditLog
from trading.symbol_health import SymbolRecovery, classify_symbol, session_for_symbol, compute_pause_scopes, session_error_code

ACCOUNT = 'DUQ503649'
ENDS = {'orders', 'completed_orders', 'executions', 'positions'}


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite broker quantity')
    return result


class PaperSafetyMonitor:
    def __init__(self, audit_path, recovery_path, *, symbols, required_bars,
                 bar_seconds=60, clock=time.time, collision_alert_seconds=60,
                 strategy_dependencies=None, system_safety=None, system_safety_provider=None):
        if not symbols or required_bars < 1 or bar_seconds != 60:
            raise ValueError('Use existing 60-second K-line strategy and its approved warmup')
        self.clock, self.lock = clock, threading.RLock()
        self.strategy_dependencies = strategy_dependencies or {'classic_conservative_trend':{s:(s,) for s in symbols}}
        self.system_safety = dict(system_safety or {})
        self.system_safety_provider=system_safety_provider
        self._published = {}
        self.symbols = tuple(symbols)
        self.required_bars, self.bar_seconds = required_bars, bar_seconds
        self.collision_alert_seconds = collision_alert_seconds
        self.audit = AuditLog(audit_path)
        self.coordinator = RecoveryCoordinator(recovery_path, clock=clock)
        self.incidents = IncidentStore(recovery_path, clock=clock)
        self.symbol_recovery = SymbolRecovery(recovery_path, self.symbols, clock=clock)
        with closing(self.coordinator.connect()) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_safety_state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_callback_events(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_health_samples(epoch TEXT NOT NULL,minute_bucket INTEGER NOT NULL,observed REAL NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(epoch,minute_bucket))')
            row = c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
            transition_seq=c.execute("SELECT COALESCE(MAX(json_extract(payload,'$.transition_sequence')),0) FROM paper_callback_events WHERE kind='pause_transition'").fetchone()[0]
        prior = json.loads(row[0]) if row else {}
        if prior.get('subscription_lifecycle_version')!=1 and prior.get('collision_since') is not None:
            for symbol in self.symbols:
                self.symbol_recovery.lifecycle.seed_legacy(symbol,prior.get('retries',0),prior['collision_since'])
        self.state = dict(positions=prior.get('positions', {}), orders=prior.get('orders', {}),
                          contracts=prior.get('contracts', {}),
                          connection_recovery=prior.get('connection_recovery', {}),
                          incident_signatures=prior.get('incident_signatures', {}),
                          incident_sequences=prior.get('incident_sequences', {}),
                          executions=prior.get('executions', {}), epoch=uuid.uuid4().hex,
                          connected=False, identity=False, upstream_connected=False, ends=[], dirty=True,
                          last_server_reply=0,
                          needs_recovery_sync=True, resubscribe_required=False, pause_scopes=prior.get('pause_scopes'), history_evidence={}, history_request_started=prior.get('history_request_started',{}), pause_transition_sequence=max(prior.get('pause_transition_sequence',0),transition_seq),
                          collision_since=prior.get('collision_since'), retry_at=0, retries=0,
                          subscription_lifecycle_version=1, quotes={}, bars={}, market_types={}, market_halts={}, market_errors={}, symbol_reset_at={}, legacy_collision=False,
                          reset_at=clock(), fault='STARTUP_RECONCILIATION_REQUIRED')
        self._publish()

    def _incident(self, key, reason, *, resolved=False, symbol=None, quantity=None, protection=None):
        signature = json.dumps([reason,resolved,symbol,quantity,protection],sort_keys=True)
        if self.state['incident_signatures'].get(key)==signature:
            return
        payload = dict(severity='GREEN' if resolved else 'RED', reason=reason,
                       symbol=symbol, quantity=quantity, protection_status=protection,
                       observed_at=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                       scope='PAPER_SAFETY', action_taken='Block new entries; preserve broker orders',
                       user_action='Review broker protection/session; replacement orders require explicit approval',
                       recovery_condition='Exact Paper identity, complete reconciliation, protection and fresh data/bars')
        sequence=self.state['incident_sequences'].get(key,0)+1
        self.state['incident_sequences'][key]=sequence
        identity = hashlib.sha256(json.dumps([self.state['epoch'], key, sequence, payload], sort_keys=True).encode()).hexdigest()
        self.incidents.ingest(identity, 'paper-safety:' + key, payload, resolved=resolved)
        self.state['incident_signatures'][key] = signature

    def admit_connection(self, gateway_generation, *, api_listening=None):
        """Same owner/state, bounded read-only connection attempts across restarts."""
        with self.lock:
            now=self.clock()
            budget=self.state['connection_recovery']
            if isinstance(api_listening,bool) and gateway_generation:
                previous=budget.get('api_listening') if budget.get('api_listener_generation')==gateway_generation else None
                if previous is False and api_listening is True:
                    budget['listener_ready_transition_generation']=gateway_generation
                if previous is not api_listening:
                    budget.update(api_listening=api_listening,api_listener_generation=gateway_generation)
                    self._publish()
            attempts=budget.get('attempts',0)
            if attempts>=4:
                changed_process=bool(gateway_generation and gateway_generation!=budget.get('gateway_generation'))
                listener_ready=bool(api_listening is True and gateway_generation
                    and budget.get('listener_ready_transition_generation')==gateway_generation
                    and budget.get('listener_rearm_generation')!=gateway_generation)
                if (not (changed_process or listener_ready) or now<budget.get('not_before',float('inf'))):
                    return False
                if listener_ready:budget['listener_rearm_generation']=gateway_generation
                budget.update(attempts=0,rearmed_at=now,previous_generation=budget.get('gateway_generation'),
                              rearm_reason='GATEWAY_GENERATION_CHANGED' if changed_process else 'API_LISTENER_BECAME_READY_ONCE')
                attempts=0
            if now<budget.get('not_before',0):return False
            attempts+=1
            budget.update(attempts=attempts,gateway_generation=gateway_generation,
                          last_attempt=now,not_before=now+(30,60,120,300)[attempts-1])
            self._publish()  # Reserve durably before creating the socket.
            return True

    def validate_connection(self, connected_since, *, connection_generation=None):
        """Only sustained independent account/end-marker proof closes the incident."""
        with self.lock:
            now=self.clock()
            if (now-connected_since<60 or not self._complete()
                    or not self.state.get('upstream_connected')
                    or not 0<=now-self.state.get('last_server_reply',0)<=10):
                return False
            budget=self.state['connection_recovery']
            if connection_generation and budget.get('subscription_connection_proof')!=connection_generation:
                changed=self.symbol_recovery.verified_connection(connection_generation,reconciliation_verified=True)
                budget['subscription_connection_proof']=connection_generation
                self._record('connection_dependency_restored',dict(connection=connection_generation,symbols=changed,
                    proof='Stable authenticated Paper connection and complete fresh broker reconciliation; no trading permission'))
                self._publish()
            if budget.get('attempts',0):
                budget.update(attempts=0,not_before=0,validated_at=now)
                self._publish()
            return True

    def begin(self, accounts):
        with self.lock:
            if accounts != [ACCOUNT]:
                self.invalidate('IDENTITY_MISMATCH')
                raise PermissionError('Exact DUQ503649 Paper identity required')
            self.state.update(identity=True, connected=True, upstream_connected=True, epoch=uuid.uuid4().hex,
                              last_server_reply=self.clock())
            self.start_reconciliation()

    def start_reconciliation(self):
        with self.lock:
            routine_refresh = self._complete()
            if self.state['positions']:
                self.state['last_positions'] = dict(self.state['positions'])
            self.state.update(ends=[], dirty=True, orders={}, positions={}, fault='RECONCILIATION_REQUIRED',
                              sync_started=self.clock(), sync_new_execution=False, routine_refresh=routine_refresh)
            self._publish()

    def invalidate(self, reason):
        with self.lock:
            self.state.update(connected=False, identity=False, upstream_connected=False, ends=[], dirty=True,
                              quotes={}, bars={}, history_evidence={}, reset_at=self.clock(), fault=reason)
            self._incident('connection', reason)
            self._publish()

    def error(self, code, symbol=None):
        with self.lock:
            if code == 10197:
                if self.state['collision_since'] is None:
                    self.state.update(collision_since=self.clock(), retry_at=self.clock()+30, retries=0,
                                      needs_recovery_sync=True)
                if symbol is None:
                    self.state.update(quotes={},bars={},reset_at=self.clock(),legacy_collision=True)
                else:
                    self.state['quotes'].pop(symbol,None);self.state['bars'].pop(symbol,None)
                    self.state['history_evidence'].pop(symbol,None)
                    self.state['symbol_reset_at'][symbol]=self.clock()
                self.state['fault'] = 'MARKET_DATA_COLLISION'
            elif code==1100:
                self.state.update(upstream_connected=False,ends=[],dirty=True,quotes={},bars={},
                                  fault='IBKR_UPSTREAM_CONNECTION_LOST',needs_recovery_sync=True)
                self._incident('upstream','IBKR upstream lost; preserve authenticated API socket')
                self._publish()
                return
            elif code in (1300, 502, 504):
                self.invalidate('API_CONNECTION_LOST')
                return
            elif code in (1101, 1102):
                self.state['upstream_connected']=True
                if code == 1101:
                    self.state['resubscribe_required'] = True
                self.state.update(ends=[], dirty=True, quotes={}, bars={}, reset_at=self.clock(),
                                  fault='RECONNECT_RECONCILIATION_REQUIRED', needs_recovery_sync=True)
            elif code in (110, 201, 202):
                self.state.update(dirty=True, fault='ORDER_REJECTED_OR_CANCELLED_RECONCILE')
                self._incident('order-error', 'Broker order error ' + str(code))
            self._publish()

    def order(self, order):
        with self.lock:
            if order.get('account') != ACCOUNT:
                self.invalidate('ORDER_ACCOUNT_MISMATCH')
                return
            key = str(order['order_id'])
            old = self.state['orders'].get(key, {})
            if old and any(old.get(k) and order.get(k) and old[k]!=order[k]
                           for k in ('perm_id','account','client_id','con_id','symbol','side')):
                self.invalidate('ORDER_IDENTITY_CONFLICT')
                raise ValueError('Broker order identity conflict')
            merged = {**old, **order}
            # Never regress known cumulative fills or resurrect terminal orders.
            if number(merged.get('filled', 0)) < number(old.get('filled', 0)):
                self.state.update(dirty=True, fault='OUT_OF_ORDER_STATUS')
                self._publish()
                return
            if old.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive') and merged.get('status') not in ('Filled','Cancelled','ApiCancelled','Inactive'):
                self.state.update(dirty=True, fault='OUT_OF_ORDER_STATUS')
                self._publish()
                return
            self.state['orders'][key] = merged
            self._record('order',merged)
            if set(self.state['ends']) == ENDS and number(merged.get('filled',0)) > number(old.get('filled',0)):
                self.state.update(dirty=True, fault='FILL_STATUS_REQUIRES_POSITION_RECONCILIATION')
            if merged.get('status') in ('Inactive','Cancelled','ApiCancelled') and str(merged.get('order_type','')).startswith('STP'):
                self._incident('stop:' + merged['symbol'], 'Protective stop rejected or cancelled',
                               symbol=merged['symbol'], quantity=merged.get('remaining'), protection='UNPROTECTED')
            self._publish()

    def execution(self, execution):
        with self.lock:
            if execution.get('account') != ACCOUNT or not execution.get('exec_id'):
                self.invalidate('EXECUTION_IDENTITY_MISMATCH')
                raise ValueError('Execution account/execId required')
            key = execution['exec_id']
            old = self.state['executions'].get(key)
            if old is not None and old != execution:
                self.invalidate('EXECUTION_ID_CONFLICT')
                raise ValueError('Conflicting duplicate execId')
            # Existing unique execId and identity checks, durable before permission.
            try:
                with closing(self.audit._connect()) as c, c:
                    self.audit._upsert_execution(c, execution, datetime.fromtimestamp(self.clock(), timezone.utc).isoformat())
            except Exception:
                self.invalidate('AUDIT_EXECUTION_PERSISTENCE_FAILED')
                raise
            self.state['executions'][key] = execution
            self._record('execution',execution)
            if old is None and set(self.state['ends']) == ENDS:
                self.state.update(dirty=True, fault='NEW_EXECUTION_REQUIRES_POSITION_RECONCILIATION')
            elif old is None:
                self.state['sync_new_execution'] = True
            self._publish()

    def position(self, symbol, quantity, account=ACCOUNT, *, con_id=0, currency='', sec_type=''):
        with self.lock:
            if account != ACCOUNT:
                self.invalidate('POSITION_ACCOUNT_MISMATCH')
                return
            qty = number(quantity)
            if qty != self.state['positions'].get(symbol, 0) and set(self.state['ends']) == ENDS:
                self.state.update(dirty=True, fault='POSITION_CHANGE_REQUIRES_RECONCILIATION')
            self.state['positions'][symbol] = qty
            contract = dict(con_id=con_id,currency=currency,sec_type=sec_type)
            prior = self.state['contracts'].get(symbol)
            if prior and prior != contract:
                self.invalidate('POSITION_CONTRACT_CONFLICT')
                raise ValueError('Ambiguous symbol contract')
            self.state['contracts'][symbol] = contract
            self._publish()

    def end(self, kind):
        with self.lock:
            if kind not in ENDS or not self.state['connected'] or not self.state['identity']:
                return
            self.state['ends'] = sorted(set(self.state['ends']) | {kind})
            if set(self.state['ends']) == ENDS:
                dirty = self.state.get('sync_new_execution',False)
                self.state.update(dirty=dirty, reconciled_at=self.clock(),
                                  fault='FILL_DURING_SNAPSHOT_REQUIRES_REPEAT_READBACK' if dirty else None)
                if not dirty:
                    self.state['needs_recovery_sync'] = False
                    self._incident('reconciliation', 'Complete broker position/order/execution readback', resolved=True)
                    self._incident('connection', 'Exact Paper identity and complete broker readback restored', resolved=True)
            self._publish()

    def quote(self, symbol, bid, ask, bid_at, ask_at, data_type, *, last=None, last_at=None, event_time=None):
        with self.lock:
            self.state['last_server_reply'] = self.clock()
            self.state['quotes'][symbol] = dict(bid=bid, ask=ask, bid_at=bid_at, ask_at=ask_at, data_type=data_type,
                                                last=last,last_at=last_at,event_time=event_time)
            self._publish()

    def bar(self, symbol, started, ended):
        with self.lock:
            now = self.clock()
            self.state['last_server_reply'] = now
            if ended > now or ended-started != self.bar_seconds or started < self.state['symbol_reset_at'].get(symbol,self.state['reset_at']):
                return
            bars = self.state['bars'].setdefault(symbol, [])
            if ended not in bars:
                if bars and ended-bars[-1] != self.bar_seconds:
                    bars.clear()
                bars.append(ended)
                del bars[:-self.required_bars]
            self._publish()

    def retry_due(self):
        """Caller may retry data subscriptions only; never login/restart/cancel orders."""
        with self.lock:
            now = self.clock()
            if self.state['collision_since'] is None or not self.state['connected'] or now < self.state['retry_at'] or self.state['retries']>=4:
                return False
            self.state['retries'] += 1
            delay = (30,60,120,300)[min(self.state['retries'],3)]
            self.state['retry_at'] = now+delay
            self._publish()
            return True

    def market_error(self, symbol, code, details):
        with self.lock:
            # A cancellation acknowledgement is not a new recovery failure.
            if code==162 and 'cancel' in str(details).lower():return
            code=session_error_code(code,details)
            # An unrelated history error cannot replace a current quote-session
            # conflict and suppress the existing read-only recovery policy.
            if code in (162,321) and self.state['market_errors'].get(symbol,{}).get('code')==10197:
                self.symbol_recovery.error(symbol,code,details)
                return
            self.state['market_errors'][symbol]=dict(code=code,details=str(details),observed_at=self.clock())
            shared = code==10197 and all(self.state['market_errors'].get(s,{}).get('code')==10197
                and 0<=self.clock()-self.state['market_errors'][s]['observed_at']<=60 for s in self.symbols)
            self.symbol_recovery.error(symbol,code,details,confirmed_shared=shared)

    def symbol_health(self):
        bucket=int(self.clock())
        if getattr(self,'_session_bucket',None)!=bucket:
            self._session_bucket=bucket;self._session_value=session_for_symbol(self.clock())
        session=self._session_value
        result = {symbol:classify_symbol({**self.state['quotes'].get(symbol,{}),
                    'data_type':self.state['market_types'].get(symbol,self.state['quotes'].get(symbol,{}).get('data_type')),
                    'permission_denied':self.state['market_errors'].get(symbol,{}).get('code') in (354,10168,10186)},
                    self.clock(),session=session,halted=self.state['market_halts'].get(symbol)) for symbol in self.symbols}
        for symbol,h in result.items():
            policy=getattr(self,'_market_policies',{}).get(symbol,{})
            if policy.get('fault_active',True):
                h['allows_realtime']=False
                h['recovery_phase']=policy.get('phase','UNVALIDATED')
        return result

    def poll_symbol_recovery(self):
        """Single service owner calls at heartbeat cadence; no extra threads/requests."""
        with self.lock:
            health=self.symbol_health();actions=[]
            for symbol,h in health.items():
                q={**self.state['quotes'].get(symbol,{}),'data_type':self.state['market_types'].get(symbol),
                   'permission_denied':h['status']=='PERMISSION_DENIED',
                   'request_id':46000+self.symbols.index(symbol),'requested_type':1,
                   'exchange':'SMART','sec_type':'STK','currency':'USD',
                   'con_id':self.state['contracts'].get(symbol,{}).get('con_id')}
                policy=self.symbol_recovery.observe(symbol,q,session=h['session'],halted=h['halted'],
                    reconciliation_verified=bool(self._complete() and 0<=self.clock()-self.state.get('reconciled_at',0)<=30))
                if not hasattr(self,'_market_policies'):self._market_policies={}
                self._market_policies[symbol]=policy
                self.symbol_recovery.verified_recovery(symbol)
                action=self.symbol_recovery.retry_due(symbol,session=h['session'],connected=self.state['connected'] and self.state['identity'] and self.state['upstream_connected'])
                if action:actions.append(action)
            return actions

    def protection(self):
        complete = self._complete()
        result = {}
        positions = self.state['positions'] if complete else {**self.state.get('last_positions',{}), **self.state['positions']}
        for symbol, qty in positions.items():
            if not qty:
                continue
            status, covered = 'PROTECTION_UNKNOWN', 0.0
            contract = self.state['contracts'].get(symbol,{})
            if complete and qty > 0 and contract.get('con_id') and contract.get('currency')=='USD' and contract.get('sec_type')=='STK':
                ambiguous = False
                perm_ids = set()
                for order in self.state['orders'].values():
                    if order.get('symbol') != symbol or order.get('side') != 'SELL' or not str(order.get('order_type','')).startswith('STP'):
                        continue
                    if order.get('status') not in ('Submitted','PreSubmitted'):
                        continue
                    if order.get('completed'):
                        continue
                    if any(order.get(k)!=contract.get(k) for k in ('con_id','currency','sec_type')):
                        ambiguous = True
                        continue
                    if order.get('transmit') is not True or not order.get('perm_id'):
                        continue
                    if order['perm_id'] in perm_ids:
                        ambiguous = True
                        continue
                    perm_ids.add(order['perm_id'])
                    parent = order.get('parent_id', 0)
                    if parent:
                        p = self.state['orders'].get(str(parent),{})
                        if (p.get('status')!='Filled' or p.get('account')!=ACCOUNT
                                or p.get('symbol')!=symbol or p.get('con_id')!=contract['con_id']
                                or p.get('side')!='BUY' or p.get('client_id',0)!=order.get('client_id',0)):
                            ambiguous = True
                            continue
                    if order.get('oca_group') or order.get('remaining') is None:
                        ambiguous = True
                        continue
                    covered += max(0,number(order['remaining']))
                if not ambiguous and covered <= qty:
                    status = 'PROTECTED' if covered == qty else 'PARTIALLY_PROTECTED' if covered else 'UNPROTECTED'
            result[symbol] = dict(quantity=qty, covered_quantity=covered, status=status)
        # New fills before a complete position refresh cannot disappear from alerts.
        if not complete:
            for execution in self.state['executions'].values():
                symbol = execution['symbol']
                if symbol not in result and execution.get('side') in ('BOT','BUY'):
                    result[symbol] = dict(quantity=execution['shares'], covered_quantity=0, status='PROTECTION_UNKNOWN')
        return result

    def pause_projection(self, health, protection, complete):
        now=self.clock()
        bars_ready={}
        for symbol in set(self.symbols)|set(health):
            ends=self.state['bars'].get(symbol,[])[-self.required_bars:]
            bars_ready[symbol]=(len(ends)>=self.required_bars and all(b-a==60 for a,b in zip(ends,ends[1:]))
                                and 0<=now-ends[-1]<=65)
            history=self.state.get('history_evidence',{}).get(symbol,{})
            history_ends=history.get('completed_ends',[])[-self.required_bars:]
            history_ok=(history.get('complete') is True and len(history_ends)>=self.required_bars
                and all(b-a==60 for a,b in zip(history_ends,history_ends[1:]))
                and 0<=now-history_ends[-1]<=65 and 0<=now-history.get('received_at',0)<=65
                and history.get('received_at',0)>=self.state['symbol_reset_at'].get(symbol,self.state['reset_at']))
            bars_ready[symbol]=bool(bars_ready[symbol] or history_ok)
        fresh_reconciliation=bool(complete and 0<=now-self.state.get('reconciled_at',0)<=30)
        dynamic={}
        if self.system_safety_provider is not None:
            try:dynamic=dict(self.system_safety_provider())
            except Exception:dynamic=dict(control_verified=False,global_risk_verified=False,authoritative_state_verified=False,risk_isolatable=False)
        system={**self.system_safety,**dynamic,
            'identity_verified':bool(self.state['identity']),
            'broker_connected':bool(self.state['connected'] and self.state['upstream_connected'] and 0<=now-self.state['last_server_reply']<=10),
            'reconciliation_verified':fresh_reconciliation,
            'authoritative_state_verified':bool(fresh_reconciliation and dynamic.get('authoritative_state_verified',self.system_safety.get('authoritative_state_verified')) is True)}
        risks={}
        for symbol in set(self.symbols)|set(protection):
            uncertain=any(o.get('symbol')==symbol and (o.get('status') in ('Unknown','UNKNOWN','PendingCancel','ApiPending','PendingSubmit')
                or (o.get('status') in ('Submitted','PreSubmitted') and o.get('remaining') is None)) for o in self.state['orders'].values())
            risks[symbol]=bool(fresh_reconciliation and system.get('global_risk_verified') is True and not uncertain
                and (symbol not in protection or protection[symbol]['status']=='PROTECTED'))
        return compute_pause_scopes(health,self.strategy_dependencies,system,now=now,kline_ready=bars_ready,symbol_risk=risks)

    def _record_pause(self, payload):
        self.state['pause_transition_sequence']+=1
        self._record('pause_transition',dict(payload,transition_sequence=self.state['pause_transition_sequence']))

    def record_pause_transitions(self, current):
        previous=self.state.get('pause_scopes') or {}
        def keyed(value):
            return {json.dumps([r['scope'],r['affected_symbols'],r['affected_strategies']],sort_keys=True):r for r in value.get('pauses',[])}
        old,new=keyed(previous),keyed(current)
        for key,row in new.items():
            if key not in old:
                self._record_pause(dict(action='PAUSE',**row))
        for key,row in old.items():
            if key not in new:
                self._record_pause(dict(action='PAUSE_SCOPE_CLEARED',**{**row,'reason':'This scope cleared; per-trade recovery decisions remain authoritative'}))
        for strategy,rows in current['decisions'].items():
            for symbol,decision in rows.items():
                prior=previous.get('decisions',{}).get(strategy,{}).get(symbol)
                if prior and prior.get('allowed') is False and decision['allowed'] is True:
                    self._record_pause(dict(action='RESUME',scope='SCOPED_TRADE_RECOVERED',
                        affected_symbols=[symbol],affected_strategies=[strategy],reason=decision['reason'],
                        recovery_conditions=['Freshness, K-lines, account/order and risk checks verified']))
        self.state['pause_scopes']=current
        self.state['strategy_dependencies']=self.strategy_dependencies
        from trading.signal_scheduler import dependency_fingerprint
        self.state['strategy_dependency_fingerprint']=dependency_fingerprint(self.strategy_dependencies)

    def snapshot(self):
        now = self.clock()
        protection = self.protection()
        complete = self._complete()
        covered = complete and all(p['status']=='PROTECTED' for p in protection.values())
        data = True
        for symbol in self.symbols:
            q = self.state['quotes'].get(symbol,{})
            bars = self.state['bars'].get(symbol,[])
            try:
                fresh = q['data_type']==1 and 0<number(q['bid'])<=number(q['ask']) and all(0<=now-q[k]<=5 and q[k]>=self.state['reset_at'] for k in ('bid_at','ask_at'))
            except (KeyError,TypeError,ValueError):
                fresh = False
            data = data and fresh and len(bars)>=self.required_bars and 0<=now-bars[-1]<=self.bar_seconds+5
        health=self.symbol_health()
        scopes=self.pause_projection(health,protection,complete)
        return dict(account=ACCOUNT, environment='PAPER', observed_at=now, epoch=self.state['epoch'],
                    protection=protection, symbol_health=health, pause_scopes=scopes,
                    entries_ready_scope='AGGREGATE_REPORT_ONLY; scoped trade decisions are authoritative for market isolation',
                    protection_ready=bool(covered), reconciliation_complete=bool(complete),
                    data_ready=bool(data), entries_ready=bool(covered and data and not self.state['needs_recovery_sync']), fault=self.state['fault'])

    def _record(self, kind, payload):
        encoded=json.dumps(payload,sort_keys=True)
        identity=hashlib.sha256((self.state['epoch']+kind+encoded).encode()).hexdigest()
        with closing(self.coordinator.connect()) as c, c:
            c.execute('INSERT OR IGNORE INTO paper_callback_events VALUES (?,?,?,?)',
                      (identity,kind,encoded,self.clock()))

    def _complete(self):
        return (self.state['connected'] and self.state['identity'] and self.state['upstream_connected']
                and 0<=self.clock()-self.state['last_server_reply']<=10
                and set(self.state['ends'])==ENDS and not self.state['dirty'])

    def _publish(self):
        snapshot = self.snapshot()
        self.record_pause_transitions(snapshot['pause_scopes'])
        if snapshot['data_ready'] and self.state['collision_since'] is not None:
            self.state['collision_since'] = None
            self._incident('collision', 'Fresh live data and completed K-lines verified; trading permission remains separate', resolved=True)
        elif self.state['legacy_collision'] and self.state['collision_since'] is not None and self.clock()-self.state['collision_since']>=self.collision_alert_seconds:
            self._incident('collision', 'Prolonged IBKR 10197 market-data collision')
        # Routine polling invalidates permissions immediately, but is not a new
        # protection incident while a healthy snapshot is being replaced. Genuine
        # loss, changed exposure, new executions or a 30s timeout still alert.
        routine_pending = (self.state.get('routine_refresh', False)
            and not snapshot['reconciliation_complete']
            and self.state['connected'] and self.state['identity']
            and 0 <= self.clock()-self.state['last_server_reply'] <= 10
            and 0 <= self.clock()-self.state.get('sync_started', 0) <= 30
            and self.state['fault']=='RECONCILIATION_REQUIRED'
            and not self.state.get('sync_new_execution', False)
            and all(q==self.state.get('last_positions',{}).get(sym)
                    for sym,q in self.state['positions'].items()))
        for symbol, item in snapshot['protection'].items():
            if routine_pending and item['status']=='PROTECTION_UNKNOWN':
                continue
            self._incident('protection:' + symbol, item['status'], resolved=item['status']=='PROTECTED',
                           symbol=symbol, quantity=item['quantity'], protection=item['status'])
        # A fully reconciled flat position with no active order has no remaining
        # protection exposure. Do not leave its old incident open forever after
        # an exit, and never infer this from an incomplete/dirty snapshot.
        if self._complete():
            for key in tuple(self.state['incident_signatures']):
                if not key.startswith('protection:'):continue
                symbol=key.split(':',1)[1]
                if number(self.state['positions'].get(symbol,0))!=0:continue
                if any(o.get('symbol')==symbol and not o.get('completed')
                       and o.get('status') not in ('Filled','Cancelled','ApiCancelled','Inactive')
                       for o in self.state['orders'].values()):continue
                self._incident(key,'Complete broker reconciliation confirms no position or open order',
                               resolved=True,symbol=symbol,quantity=0,protection='NO_EXPOSURE')
        if self.state['connected'] and self.state.get('sync_started') is not None and self.clock()-self.state['sync_started']>30 and not snapshot['reconciliation_complete']:
            self._incident('reconciliation', 'Broker reconciliation incomplete or failed')
        now=self.clock();bucket=int(now//60)
        sample_due=getattr(self,'_health_sample_bucket',None)!=bucket
        with closing(self.coordinator.connect()) as c, c:
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES (1,?)', (json.dumps(self.state,sort_keys=True),))
            if sample_due:
                sample=dict(account=ACCOUNT,environment='PAPER',observed_at=now,
                    api_connected=self.state['connected'],upstream_connected=self.state['upstream_connected'],
                    identity_verified=self.state['identity'],server_reply_at=self.state['last_server_reply'],
                    reconciliation_complete=snapshot['reconciliation_complete'],
                    data_ready=snapshot['data_ready'],entries_ready=snapshot['entries_ready'],
                    fault=self.state['fault'],market={},pause_reasons=[dict(scope=r['scope'],reason=r['reason'])
                        for r in snapshot['pause_scopes'].get('pauses',[])])
                for symbol,health in snapshot['symbol_health'].items():
                    quote=self.state['quotes'].get(symbol,{})
                    sample['market'][symbol]={**{k:health.get(k) for k in ('status','session','allows_realtime')},
                        'data_type':self.state['market_types'].get(symbol,quote.get('data_type')),
                        'bid_at':quote.get('bid_at'),'ask_at':quote.get('ask_at')}
                c.execute('INSERT OR IGNORE INTO paper_health_samples VALUES (?,?,?,?)',
                    (self.state['epoch'],bucket,now,json.dumps(sample,sort_keys=True)))
        if sample_due:self._health_sample_bucket=bucket
        for module, ready in (('PROTECTION',snapshot['protection_ready']), ('PAPER_SESSION',snapshot['entries_ready'])):
            if not ready and self._published.get(module) is False:
                continue  # A held gate needs no repeated downstream invalidation events.
            self.coordinator.observe(module, 'HEALTHY' if ready else 'DEGRADED', freshness='FRESH',
                                     reason='Paper callback safety evidence', account=ACCOUNT, environment='PAPER',
                                     safety_snapshot=snapshot)
            self._published[module] = ready
        return snapshot
