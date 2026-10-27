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

ACCOUNT = 'DUQ503649'
ENDS = {'orders', 'completed_orders', 'executions', 'positions'}


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite broker quantity')
    return result


class PaperSafetyMonitor:
    def __init__(self, audit_path, recovery_path, *, symbols, required_bars,
                 bar_seconds=60, clock=time.time, collision_alert_seconds=60):
        if not symbols or required_bars < 1 or bar_seconds != 60:
            raise ValueError('Use existing 60-second K-line strategy and its approved warmup')
        self.clock, self.lock = clock, threading.RLock()
        self._published = {}
        self.symbols = tuple(symbols)
        self.required_bars, self.bar_seconds = required_bars, bar_seconds
        self.collision_alert_seconds = collision_alert_seconds
        self.audit = AuditLog(audit_path)
        self.coordinator = RecoveryCoordinator(recovery_path, clock=clock)
        self.incidents = IncidentStore(recovery_path, clock=clock)
        with closing(self.coordinator.connect()) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_safety_state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_callback_events(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,observed REAL NOT NULL)')
            row = c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        prior = json.loads(row[0]) if row else {}
        self.state = dict(positions=prior.get('positions', {}), orders=prior.get('orders', {}),
                          contracts=prior.get('contracts', {}),
                          incident_signatures=prior.get('incident_signatures', {}),
                          executions=prior.get('executions', {}), epoch=uuid.uuid4().hex,
                          connected=False, identity=False, ends=[], dirty=True,
                          last_server_reply=0,
                          needs_recovery_sync=True,
                          collision_since=prior.get('collision_since'), retry_at=0, retries=0,
                          quotes={}, bars={}, reset_at=clock(), fault='STARTUP_RECONCILIATION_REQUIRED')
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
        identity = hashlib.sha256(json.dumps([self.state['epoch'], key, payload], sort_keys=True).encode()).hexdigest()
        self.incidents.ingest(identity, 'paper-safety:' + key, payload, resolved=resolved)
        self.state['incident_signatures'][key] = signature

    def begin(self, accounts):
        with self.lock:
            if accounts != [ACCOUNT]:
                self.invalidate('IDENTITY_MISMATCH')
                raise PermissionError('Exact DUQ503649 Paper identity required')
            self.state.update(identity=True, connected=True, epoch=uuid.uuid4().hex,
                              last_server_reply=self.clock())
            self.start_reconciliation()

    def start_reconciliation(self):
        with self.lock:
            if self.state['positions']:
                self.state['last_positions'] = dict(self.state['positions'])
            self.state.update(ends=[], dirty=True, orders={}, positions={}, fault='RECONCILIATION_REQUIRED',
                              sync_started=self.clock(), sync_new_execution=False)
            self._publish()

    def invalidate(self, reason):
        with self.lock:
            self.state.update(connected=False, identity=False, ends=[], dirty=True,
                              quotes={}, bars={}, reset_at=self.clock(), fault=reason)
            self._incident('connection', reason)
            self._publish()

    def error(self, code):
        with self.lock:
            if code == 10197:
                if self.state['collision_since'] is None:
                    self.state.update(collision_since=self.clock(), retry_at=self.clock()+30, retries=0,
                                      quotes={}, bars={}, reset_at=self.clock(), needs_recovery_sync=True)
                self.state['fault'] = 'MARKET_DATA_COLLISION'
            elif code in (1100, 1300, 502, 504):
                self.invalidate('API_CONNECTION_LOST')
                return
            elif code in (1101, 1102):
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

    def quote(self, symbol, bid, ask, bid_at, ask_at, data_type):
        with self.lock:
            self.state['last_server_reply'] = self.clock()
            self.state['quotes'][symbol] = dict(bid=bid, ask=ask, bid_at=bid_at, ask_at=ask_at, data_type=data_type)
            self._publish()

    def bar(self, symbol, started, ended):
        with self.lock:
            now = self.clock()
            self.state['last_server_reply'] = now
            if ended > now or ended-started != self.bar_seconds or started < self.state['reset_at']:
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
            if self.state['collision_since'] is None or not self.state['connected'] or now < self.state['retry_at']:
                return False
            self.state['retries'] += 1
            delay = (30,60,120,300)[min(self.state['retries'],3)]
            self.state['retry_at'] = now+delay
            self._publish()
            return True

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
        return dict(account=ACCOUNT, environment='PAPER', observed_at=now, epoch=self.state['epoch'],
                    protection=protection, protection_ready=bool(covered), reconciliation_complete=bool(complete),
                    data_ready=bool(data), entries_ready=bool(covered and data and not self.state['needs_recovery_sync']), fault=self.state['fault'])

    def _record(self, kind, payload):
        encoded=json.dumps(payload,sort_keys=True)
        identity=hashlib.sha256((self.state['epoch']+kind+encoded).encode()).hexdigest()
        with closing(self.coordinator.connect()) as c, c:
            c.execute('INSERT OR IGNORE INTO paper_callback_events VALUES (?,?,?,?)',
                      (identity,kind,encoded,self.clock()))

    def _complete(self):
        return (self.state['connected'] and self.state['identity']
                and 0<=self.clock()-self.state['last_server_reply']<=10
                and set(self.state['ends'])==ENDS and not self.state['dirty'])

    def _publish(self):
        snapshot = self.snapshot()
        if snapshot['entries_ready'] and self.state['collision_since'] is not None:
            self.state['collision_since'] = None
            self._incident('collision', 'Fresh live data, completed K-lines, broker reconciliation and protection verified', resolved=True)
        elif self.state['collision_since'] is not None and self.clock()-self.state['collision_since']>=self.collision_alert_seconds:
            self._incident('collision', 'Prolonged IBKR 10197 market-data collision')
        for symbol, item in snapshot['protection'].items():
            self._incident('protection:' + symbol, item['status'], resolved=item['status']=='PROTECTED',
                           symbol=symbol, quantity=item['quantity'], protection=item['status'])
        if self.state['connected'] and self.state.get('sync_started') is not None and self.clock()-self.state['sync_started']>30 and not snapshot['reconciliation_complete']:
            self._incident('reconciliation', 'Broker reconciliation incomplete or failed')
        with closing(self.coordinator.connect()) as c, c:
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES (1,?)', (json.dumps(self.state,sort_keys=True),))
        for module, ready in (('PROTECTION',snapshot['protection_ready']), ('PAPER_SESSION',snapshot['entries_ready'])):
            if not ready and self._published.get(module) is False:
                continue  # A held gate needs no repeated downstream invalidation events.
            self.coordinator.observe(module, 'HEALTHY' if ready else 'DEGRADED', freshness='FRESH',
                                     reason='Paper callback safety evidence', account=ACCOUNT, environment='PAPER',
                                     safety_snapshot=snapshot)
            self._published[module] = ready
        return snapshot
