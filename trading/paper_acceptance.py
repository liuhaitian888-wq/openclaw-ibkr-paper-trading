"""Finite explicitly approved Paper acceptance scope; no strategy enablement."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sqlite3

ACCOUNT = 'DUQ503649'
CLIENT_ID = 19880
STAGES = ('cancel', 'fill', 'close')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def validate_scope(scope, actual, root, now=None):
    now = now or datetime.now(timezone.utc)
    if (scope.get('approved') is not True or scope.get('environment') != 'PAPER'
            or scope.get('account') != ACCOUNT or scope.get('symbol') != 'NVDA'
            or scope.get('client_id') != CLIENT_ID or scope.get('quantity') != 1
            or scope.get('max_limit') != 200 or scope.get('max_submissions') != 3
            or scope.get('maintenance_test_authorized') is not True
            or scope.get('grants_strategy_permission') is not False
            or scope.get('id') != 'pa-20261106-nvda-v1'
            or any(scope.get(k) != actual.get(k) or not actual.get(k)
                   for k in ('commit', 'branch', 'code_root', 'state_root'))):
        raise PermissionError('Exact approved finite Paper scope required')
    age=(datetime.fromisoformat(scope['expires_at'])-now).total_seconds()
    if not 0 < age <= 7200:
        raise PermissionError('Test authorization expired or unbounded')
    for name, digest in scope.get('preserved_files', {}).items():
        if name not in ('production.json', 'PAUSED', 'runtime/MAINTENANCE'):
            raise PermissionError('Unexpected preserved gate path')
        p=root/name
        current=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'ABSENT'
        if current != digest:
            raise PermissionError('Global execution gate changed')
    if set(scope.get('preserved_files', {})) != {'production.json','PAUSED','runtime/MAINTENANCE'}:
        raise PermissionError('Preserved global gate hashes required')


def check_order(stage, *, bid, ask, bid_at, ask_at, data_type, limit, min_tick,
                position, baseline, usd_cash, available_funds, orders, now, funding_capacity_usd=None):
    if stage not in STAGES or baseline != 0:
        raise PermissionError('Explicit stage and flat initial NVDA required')
    values=(bid,ask,bid_at,ask_at,limit,min_tick,usd_cash,available_funds,position)
    if not all(math.isfinite(float(x)) for x in values):
        raise PermissionError('Finite broker facts required')
    if data_type != 1 or not 0 < bid <= ask or ask/bid-1 > .01:
        raise PermissionError('Fresh tight real-time quotes required')
    if not all(0 <= now-t <= 3 for t in (bid_at,ask_at)):
        raise PermissionError('Quote stale or from future')
    if not 0 < limit <= 200 or min_tick <= 0:
        raise PermissionError('Paper limit outside scope')
    if Decimal(str(limit)) % Decimal(str(min_tick)) != 0:
        raise PermissionError('Price not on broker minimum tick')
    if position != (1 if stage == 'close' else 0):
        raise PermissionError('Unexpected test symbol position')
    if available_funds <= 0:
        raise PermissionError('No broker available funds')
    reserved=0
    for order in orders:
        if order['account'] != ACCOUNT or order.get('symbol') == 'NVDA':
            raise PermissionError('Unreconciled account or existing NVDA order')
        if order['side']=='BUY':
            if order.get('currency') != 'USD' or order.get('order_type') != 'LMT' or order.get('limit',0)<=0:
                raise PermissionError('External buy reservation cannot be bounded')
            reserved += order['remaining']*order['limit']+2
        elif order['side']!='SELL' or order['remaining'] > order.get('held_position',0):
            raise PermissionError('External exposure is ambiguous or short')
    capacity=usd_cash if funding_capacity_usd is None else funding_capacity_usd
    if not math.isfinite(float(capacity)):raise PermissionError('Invalid funding capacity')
    if stage != 'close' and capacity-reserved < limit+2:
        raise PermissionError('USD cash must cover order, existing buys and fee buffer')
    return dict(side='SELL' if stage=='close' else 'BUY', quantity=1,
                limit=limit, reserved_usd=0 if stage=='close' else limit+2,
                existing_buy_reservations=reserved)


class Journal:
    """Atomic test intent/audit reservation before any order transport."""
    def __init__(self, audit_path, scope_id):
        self.path=Path(audit_path);self.scope_id=scope_id
        if not self.path.is_file():raise PermissionError('Existing canonical audit required')
        with closing(self.connect()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_acceptance_attempts (ref TEXT PRIMARY KEY, scope TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS paper_acceptance_events (id INTEGER PRIMARY KEY, ref TEXT NOT NULL, occurred_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
    def connect(self):return sqlite3.connect(self.path,timeout=2)
    def read(self,stage):
        with closing(self.connect()) as c:
            row=c.execute('SELECT status,payload FROM paper_acceptance_attempts WHERE ref=?',(self.scope_id+':'+stage,)).fetchone()
            return {**json.loads(row[1]),'status':row[0]} if row else None
    def reserve(self,stage,payload):
        if stage not in STAGES:raise ValueError('Unknown test stage')
        ref=self.scope_id+':'+stage
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM paper_acceptance_attempts WHERE ref=?',(ref,)).fetchone():
                raise PermissionError('Existing attempt must be reconciled; never replay')
            if c.execute("SELECT 1 FROM order_requests WHERE status IN ('RESERVED','STARTED','UNKNOWN','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED')").fetchone():
                raise PermissionError('Another pending or uncertain broker intent exists')
            previous='cancel' if stage=='fill' else 'fill' if stage=='close' else None
            if previous:
                row=c.execute('SELECT status FROM paper_acceptance_attempts WHERE ref=?',(self.scope_id+':'+previous,)).fetchone()
                if not row or row[0] != ('CANCELLED' if previous=='cancel' else 'FILLED'):
                    raise PermissionError('Previous stage not reconciled')
            if c.execute('SELECT count(*) FROM paper_acceptance_attempts WHERE scope=?',(self.scope_id,)).fetchone()[0]>=3:
                raise PermissionError('Finite submission budget exhausted')
            encoded=json.dumps(payload,sort_keys=True)
            c.execute('INSERT INTO paper_acceptance_attempts VALUES (?,?,?,?,?)',(ref,self.scope_id,stage,'STARTED',encoded))
            c.execute('INSERT INTO order_requests VALUES (?,?,?,?,?,?)',(ref,stamp(),'PAPER_ACCEPTANCE','STARTED',encoded,'Finite explicit user test; no strategy permission'))
        self.event(ref,'INTENT_RESERVED',payload)
        return ref
    def event(self,ref,kind,payload):
        with closing(self.connect()) as c,c:
            occurred=stamp();encoded=json.dumps(payload,default=str,sort_keys=True)
            c.execute('INSERT INTO paper_acceptance_events(ref,occurred_at,kind,payload) VALUES (?,?,?,?)',(ref,occurred,kind,encoded))
            c.execute('INSERT INTO order_events(idempotency_key,occurred_at,event_type,status,details) VALUES (?,?,?,?,?)',
                      (ref,occurred,kind,payload.get('status','RECORDED'),encoded))
    def finish(self,ref,status,payload):
        if status not in ('CANCELLED','FILLED','REJECTED','UNKNOWN'):raise ValueError('Explicit native outcome required')
        with closing(self.connect()) as c,c:
            row=c.execute('SELECT payload FROM paper_acceptance_attempts WHERE ref=?',(ref,)).fetchone()
            previous=json.loads(row[0]);previous.update(payload)
            c.execute('UPDATE paper_acceptance_attempts SET status=?,payload=? WHERE ref=?',(status,json.dumps(previous,default=str),ref))
            c.execute('UPDATE order_requests SET status=?,details=? WHERE idempotency_key=?',(status,json.dumps(payload,default=str),ref))
        self.event(ref,'OUTCOME_'+status,payload)


def owned_order(order, contract, ref, order_id):
    return (order.account==ACCOUNT and order.clientId==CLIENT_ID and order.orderRef==ref
            and order.orderId==order_id and contract.symbol=='NVDA' and contract.currency=='USD'
            and order.action in ('BUY','SELL') and float(order.totalQuantity)==1)


def check_session(trading_hours, timezone_id, now=None):
    from zoneinfo import ZoneInfo
    now=now or datetime.now(timezone.utc)
    local=now.astimezone(ZoneInfo(timezone_id))
    for session in trading_hours.split(';'):
        if 'CLOSED' in session:continue
        for interval in session.split(','):
            try:
                begin,end=interval.split('-')
                start=datetime.strptime(begin,'%Y%m%d:%H%M').replace(tzinfo=ZoneInfo(timezone_id))
                finish=datetime.strptime(end,'%Y%m%d:%H%M').replace(tzinfo=ZoneInfo(timezone_id))
                if start<=local<finish:return True
            except ValueError:continue
    raise PermissionError('Broker contract trading hours do not confirm current session')


def reconciled_outcome(native, *, filled, open_count, before, after, side, rejected=False):
    if native=='Filled' and filled==1 and open_count==0 and after==before+(1 if side=='BUY' else -1):
        return 'FILLED'
    if filled==0 and open_count==0 and after==before:
        if rejected or native=='Inactive':return 'REJECTED'
        if native in ('Cancelled','ApiCancelled'):return 'CANCELLED'
    return 'UNKNOWN'
