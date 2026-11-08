"""Finite reduce-only legacy protection. No cancel/entry/permission mutation."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import sqlite3
from zoneinfo import ZoneInfo

ACCOUNT='DUQ503649'
SYMBOLS={'AAPL':17,'META':100,'MSFT':13,'NIO':200,'T':3}
TERMINAL={'Filled','Cancelled','ApiCancelled','Inactive'}


def validate_scope(scope,actual,root,*,now):
    if (scope.get('id')!='legacy-protection-20261109-v1' or scope.get('approved') is not True
        or scope.get('account')!=ACCOUNT or scope.get('environment')!='PAPER'
        or scope.get('action')!='ADD_MISSING_SELL_STOP_ONLY' or scope.get('allow_during_maintenance') is not True
        or scope.get('grants_entry_permission') is not False or scope.get('max_quantities')!=SYMBOLS
        or scope.get('max_submissions')!=5 or scope.get('stop_fraction')!='0.05'
        or scope.get('client_id')!=18992 or scope.get('source_instruction')!='codex-owner:01a1bd5c:delegated-limits:20261109'
        or any(not actual.get(k) or actual[k]!=scope.get(k) for k in ('commit','branch','code_root','state_root'))):
        raise PermissionError('Exact finite owner-approved reduce-only scope required')
    try:
        uri=(root/'agent_secretary.sqlite3').absolute().as_uri()+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True,timeout=.2)) as c:
            c.execute('PRAGMA query_only=ON')
            row=c.execute('SELECT origin,kind,payload FROM secretary_events WHERE occurrence=?',(scope.get('approval_event'),)).fetchone()
        if not row or row[:2]!=('USER','PROTECTIVE_REPAIR_AUTHORIZATION') or len(row[2])>8000:
            raise PermissionError('Explicit owner protection provenance required')
        authority=json.loads(row[2])
        if (authority.get('source')!='CODEX_OWNER_CHAT' or authority.get('scope_id')!=scope['id']
            or authority.get('account')!=ACCOUNT or authority.get('max_quantities')!=SYMBOLS
            or authority.get('action')!='ADD_MISSING_SELL_STOP_ONLY'):
            raise PermissionError('Owner protection approval scope mismatch')
    except (OSError,ValueError,sqlite3.Error) as exc:
        raise PermissionError('Owner protection approval unavailable') from exc
    expires=datetime.fromisoformat(scope['expires_at'])
    if expires.tzinfo is None or not 0 < expires.timestamp()-now <= 86400:
        raise PermissionError('Protection scope expired or unbounded')
    preserved=scope.get('preserved_files',{})
    if set(preserved)!={'production.json','PAUSED','runtime/MAINTENANCE'}:raise PermissionError('Exact preserved gates required')
    for name,digest in preserved.items():
        p=root/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise PermissionError('Global gate changed; re-evaluate scope, never replay')


def regular_session(now):
    # The adapter additionally checks broker contract tradingHours/timeZoneId.
    at=datetime.fromtimestamp(now,ZoneInfo('America/New_York'))
    return at.weekday()<5 and (9,30)<=(at.hour,at.minute)<(16,0)


def plan(scope,position,orders,quote,*,now,min_tick):
    symbol=position.get('symbol')
    if symbol not in SYMBOLS or position.get('account')!=ACCOUNT:
        raise PermissionError('Only five explicitly authorized inherited holdings')
    if position.get('sec_type')!='STK' or position.get('currency')!='USD' or type(position.get('con_id')) is not int or position['con_id']<=0:
        raise PermissionError('Exact USD stock identity required')
    def dec(value):
        if isinstance(value,bool):raise PermissionError('Boolean is not a broker number')
        try:d=Decimal(str(value))
        except Exception as exc:raise PermissionError('Invalid broker number') from exc
        if not d.is_finite():raise PermissionError('Finite broker values required')
        return d
    quantity=dec(position['quantity'])
    if not 0<quantity<=scope['max_quantities'][symbol] or quantity!=quantity.to_integral_value():
        raise PermissionError('Positive whole legacy quantity within scope required')
    for order in orders:
        if order.get('completed') or order.get('status') in TERMINAL:continue
        if order.get('account')!=ACCOUNT:raise PermissionError('Mixed-account active order')
        if order.get('symbol')==symbol:
            # Any existing order prevents a new stop: no cancellation, adoption,
            # replacement or guessing whether it might later sell this exposure.
            raise PermissionError('Existing symbol order: preserve and review coverage')
    bid,ask,tick=dec(quote.get('bid')),dec(quote.get('ask')),dec(min_tick)
    if quote.get('data_type')!=1 or not 0<bid<=ask or ask/bid-1>Decimal('.02') or tick<=0:
        raise PermissionError('Fresh uncrossed tight live quote and broker tick required')
    for key in ('bid_at','ask_at'):
        age=dec(now)-dec(quote.get(key))
        if not 0<=age<=3:raise PermissionError('Quote stale or future')
    stop=(bid*(1-Decimal(scope['stop_fraction']))/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
    if not 0<stop<bid:raise PermissionError('Stop must remain below current bid')
    return {'account':ACCOUNT,'symbol':symbol,'con_id':position['con_id'],'currency':'USD','sec_type':'STK',
        'quantity':int(quantity),'stop_price':str(stop),'side':'SELL','order_type':'STP','tif':'GTC','outside_rth':False,
        'reference_bid':str(bid),'reference_ask':str(ask),'observed_at':now,
        'order_ref':scope['id']+':'+symbol+':'+str(position['con_id'])}


class Journal:
    def __init__(self,path,scope):
        self.path=path;self.scope=scope
        if not path.is_file():raise PermissionError('Existing canonical audit required')
        with closing(self.connect()) as c,c:
            c.executescript('''CREATE TABLE IF NOT EXISTS protection_repair_attempts(
                ref TEXT PRIMARY KEY,scope TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS protection_repair_events(
                id INTEGER PRIMARY KEY,ref TEXT NOT NULL,at TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL);''')
    def connect(self):return sqlite3.connect(self.path,timeout=2)
    def attempts(self):
        with closing(self.connect()) as c:
            return {r:dict(status=s,plan=json.loads(p)) for r,s,p in c.execute('SELECT ref,status,payload FROM protection_repair_attempts WHERE scope=?',(self.scope,))}
    def reserve(self,p):
        ref=p['order_ref'];encoded=json.dumps(p,sort_keys=True,allow_nan=False);stamp=datetime.now(timezone.utc).isoformat()
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM protection_repair_attempts WHERE ref=?',(ref,)).fetchone():raise PermissionError('Existing operation never replayed')
            if c.execute('SELECT count(*) FROM protection_repair_attempts WHERE scope=?',(self.scope,)).fetchone()[0]>=5:raise PermissionError('Protection budget exhausted')
            if c.execute("SELECT 1 FROM order_requests WHERE status IN ('RESERVED','STARTED','UNKNOWN','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED','PAPER_PENDING_CONFIRMATION') LIMIT 1").fetchone():raise PermissionError('Uncertain/pending global order intent')
            c.execute('INSERT INTO protection_repair_attempts VALUES (?,?,?,?)',(ref,self.scope,'STARTED',encoded))
            c.execute('INSERT INTO order_requests VALUES (?,?,?,?,?,?)',(ref,stamp,'PAPER_PROTECTIVE_REPAIR','STARTED',encoded,'Owner-authorized inherited long protection only'))
            c.execute('INSERT INTO protection_repair_events(ref,at,status,payload) VALUES (?,?,?,?)',(ref,stamp,'STARTED',encoded))
        return ref
    def finish(self,ref,status,evidence):
        if status not in ('CONFIRMED','REJECTED','UNKNOWN'):raise ValueError('Explicit outcome required')
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status FROM protection_repair_attempts WHERE ref=?',(ref,)).fetchone()
            if not row or row[0]!='STARTED':raise PermissionError('Started intent required; terminal outcomes immutable')
            c.execute('UPDATE protection_repair_attempts SET status=? WHERE ref=?',(status,ref))
            c.execute('UPDATE order_requests SET status=?,details=? WHERE idempotency_key=?',('PROTECTION_CONFIRMED' if status=='CONFIRMED' else status,json.dumps(evidence,sort_keys=True),ref))
            c.execute('INSERT INTO protection_repair_events(ref,at,status,payload) VALUES (?,?,?,?)',(ref,datetime.now(timezone.utc).isoformat(),status,json.dumps(evidence,sort_keys=True)))


async def repair_once(scope,actual,root,broker,*,now):
    """One finite attempt; injected broker owns all network resources."""
    validate_scope(scope,actual,root,now=now)
    if not regular_session(now):return {'state':'WAIT_SESSION','orders_sent':0}
    from reporting.recovery import RecoveryCoordinator
    coordinator=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
    if any(row[1]=='order' for row in coordinator.uncertainties()):
        return {'state':'RECONCILIATION_REQUIRED','orders_sent':0}
    journal=Journal(root/'trading_audit.sqlite3',scope['id'])
    attempted=journal.attempts()
    if any(v['status'] in ('STARTED','UNKNOWN') for v in attempted.values()):
        return {'state':'RECONCILIATION_REQUIRED','orders_sent':0}
    snapshot=await broker.snapshot()
    def verified(s):
        if (s.get('account')!=ACCOUNT or s.get('complete') is not True
            or set(s.get('ends',[]))!={'positions','orders','completed_orders','executions'}
            or not 0<=broker.clock()-s.get('observed_at',0)<=5
            or not 0<=broker.clock()-s.get('oldest_end_at',0)<=5):
            raise PermissionError('Fresh complete four-end Paper readback required')
        seen=set()
        for p in s.get('positions',[]):
            if p.get('account')!=ACCOUNT:raise PermissionError('Mixed-account portfolio')
            if p.get('symbol') in SYMBOLS:
                if p['symbol'] in seen:raise PermissionError('Ambiguous duplicate symbol contracts')
                seen.add(p['symbol'])
        if any(o.get('account')!=ACCOUNT for o in s.get('orders',[])):
            raise PermissionError('Mixed-account orders')
    verified(snapshot)
    candidates=[p for p in snapshot['positions'] if p.get('symbol') in SYMBOLS and float(p.get('quantity',0))>0]
    # Rotation avoids starving a symbol when another lacks entitlement.
    candidates.sort(key=lambda p:p['symbol']);slot=int(now//60)%max(1,len(candidates))
    candidates=candidates[slot:]+candidates[:slot]
    for position in candidates:
        ref=scope['id']+':'+position['symbol']+':'+str(position.get('con_id'))
        if ref in attempted:continue
        if any(o.get('symbol')==position['symbol'] and not o.get('completed') and o.get('status') not in TERMINAL for o in snapshot['orders']):continue
        try:
            details=await broker.details(position)
            from trading.paper_acceptance import check_session
            check_session(details['trading_hours'],details['timezone'],datetime.fromtimestamp(broker.clock(),timezone.utc))
            quote=await broker.quote(position)
            fresh=await broker.snapshot();verified(fresh)
            matches=[p for p in fresh['positions'] if p.get('con_id')==position['con_id'] and p.get('account')==ACCOUNT]
            if len(matches)!=1:raise PermissionError('Position changed or identity ambiguous')
            p=plan(scope,matches[0],fresh['orders'],quote,now=broker.clock(),min_tick=details['min_tick'])
            validate_scope(scope,actual,root,now=broker.clock())
        except (ValueError,KeyError,TypeError,PermissionError,TimeoutError) as exc:
            return {'state':'WAIT_EVIDENCE','symbol':position['symbol'],'reason':str(exc),'orders_sent':0}
        ref=journal.reserve(p);operation='order:'+ref
        if not coordinator.begin_operation(operation,'order',p):
            journal.finish(ref,'REJECTED',{'reason':'Other uncertain operation; no transport invoked'})
            return {'state':'RECONCILIATION_REQUIRED','orders_sent':0}
        try:
            result=await broker.submit_stop(p)
            status=result.get('status')
            if status not in ('CONFIRMED','REJECTED'):status='UNKNOWN'
        except Exception as exc:
            journal.finish(ref,'UNKNOWN',{'error_type':type(exc).__name__})
            coordinator.finish_operation(operation,'UNKNOWN')
            return {'state':'RECONCILIATION_REQUIRED','symbol':p['symbol'],'order_ref':ref,'plan':p,'native':{'error_type':type(exc).__name__},'orders_sent':1}
        except BaseException:
            journal.finish(ref,'UNKNOWN',{'error_type':'InterruptedDuringTransport'})
            coordinator.finish_operation(operation,'UNKNOWN')
            raise
        journal.finish(ref,status,result)
        coordinator.finish_operation(operation,'CONFIRMED' if status=='CONFIRMED' else 'FAILED_FINAL' if status=='REJECTED' else 'UNKNOWN')
        return {'state':status if status!='UNKNOWN' else 'RECONCILIATION_REQUIRED','symbol':p['symbol'],'order_ref':ref,'plan':p,'native':result,'orders_sent':1}
    return {'state':'NO_NEW_SAFE_REPAIR','orders_sent':0,'note':'Existing orders preserved; prior attempts never replayed. Re-evaluate broker coverage independently.'}
