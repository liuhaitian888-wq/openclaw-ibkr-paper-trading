"""Native daily stock turnover projection; never authorizes or blocks an exit transport.

This projection is deliberately separate from request commitments. A rejected request
is not a fill, and a risk-reducing sell still contributes to actual turnover.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
import re
from zoneinfo import ZoneInfo
from .entry_admission import decimal, aware_stamp


def execution_instant(value):
    if not isinstance(value,str):raise ValueError('Native execution timestamp required')
    value=value.strip()
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is not None:return parsed.astimezone(timezone.utc)
    except ValueError:pass
    match=re.fullmatch(r'(\d{8})\s+(\d{2}:\d{2}:\d{2})\s+(\S+)',value)
    if not match:raise ValueError('Explicit native execution timezone required')
    wall=datetime.strptime(match[1]+' '+match[2],'%Y%m%d %H:%M:%S')
    zone=ZoneInfo(match[3])
    options=[]
    for fold in (0,1):
        candidate=wall.replace(tzinfo=zone,fold=fold)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)==wall:
            if candidate.utcoffset() not in [x.utcoffset() for x in options]:options.append(candidate)
    if len(options)!=1:raise ValueError('Ambiguous or nonexistent local execution time')
    return options[0].astimezone(timezone.utc)


def native_turnover(connection,day,timezone_name,*,account='DUQ503649'):
    """Return exact decimal USD buys/sells and explicit unresolved evidence.

    Unknown facts are reported, never converted to zero. This function does not
    combine request promises with executions and cannot grant trading permission.
    """
    date=datetime.fromisoformat(day).date();zone=ZoneInfo(timezone_name)
    start=datetime.combine(date,time(),zone).astimezone(timezone.utc)
    end=datetime.combine(date+timedelta(days=1),time(),zone).astimezone(timezone.utc)
    buy=Decimal(0);sell=Decimal(0);ids=[];unresolved=[]
    rows=connection.execute('SELECT exec_id,raw_json,first_seen_at FROM executions WHERE account=? ORDER BY exec_id',(account,)).fetchall()
    from .execution_identity import correction_markers
    corrections=correction_markers(json.loads(row[1]) for row in rows)
    for exec_id,raw,seen in rows:
        fact=json.loads(raw)
        try:instant=execution_instant(fact.get('time'))
        except (ValueError,TypeError,KeyError):
            # A receipt predating the day proves it was already known; it cannot
            # settle today's missing timestamps, and remains in historical audit.
            try:old=aware_stamp(seen)<start.timestamp()
            except (ValueError,TypeError):old=False
            if not old:unresolved.append({'exec_id':exec_id,'reason':'EXECUTION_TIME_UNVERIFIED'})
            continue
        if not start<=instant<end:continue
        if fact.get('sec_type')=='CASH':continue
        if exec_id in corrections:
            unresolved.append({'exec_id':exec_id,'reason':'EXECUTION_CORRECTION_REQUIRES_RECONCILIATION'});continue
        if (fact.get('account')!=account or fact.get('sec_type')!='STK'
            or fact.get('currency')!='USD' or type(fact.get('con_id')) is not int or fact['con_id']<=0):
            unresolved.append({'exec_id':exec_id,'reason':'STOCK_CONTRACT_OR_USD_UNVERIFIED'});continue
        try:
            shares=decimal(fact['shares']);price=decimal(fact['price'])
            if shares<=0 or price<=0:raise ValueError('Positive native fill required')
            side=fact.get('side')
            if side in ('BUY','BOT'):buy+=shares*price
            elif side in ('SELL','SLD'):sell+=shares*price
            else:raise ValueError('Native side unverified')
            ids.append(exec_id)
        except (ValueError,TypeError,KeyError,ArithmeticError):
            unresolved.append({'exec_id':exec_id,'reason':'EXECUTION_ECONOMICS_UNVERIFIED'})
    return {'day':date.isoformat(),'timezone':timezone_name,'account':account,
            'currency':'USD','buy_notional':str(buy),'sell_notional':str(sell),
            'gross_notional':str(buy+sell),'exec_ids':ids,'unresolved':unresolved,
            'complete':not unresolved,'source':'CANONICAL_NATIVE_EXECUTIONS',
            'grants_execution_permission':False}


def admission_usage(connection,day,timezone_name):
    """Actual turnover plus still-live commitments, within caller's transaction.

    Native exits do not call this entry-only function. It reserves capacity for
    outstanding buys; it never consumes an exit authorization or cancels an order.
    """
    facts=native_turnover(connection,day,timezone_name)
    if not facts['complete']:raise PermissionError('Daily native turnover requires reconciliation: '+json.dumps(facts['unresolved']))
    zone=ZoneInfo(timezone_name);date=datetime.fromisoformat(day).date()
    start=datetime.combine(date,time(),zone).astimezone(timezone.utc)
    end=datetime.combine(date+timedelta(days=1),time(),zone).astimezone(timezone.utc)
    has_bindings=bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entry_native_bindings'").fetchone())
    commitments=Decimal(0)
    for identity,created,status,raw in connection.execute("SELECT idempotency_key,created_at,status,proposal_json FROM order_requests WHERE mode LIKE 'PAPER%' AND mode!='PAPER_CASH_CONVERSION'"):
        binding=None
        if has_bindings:
            row=connection.execute('SELECT binding FROM entry_native_bindings WHERE identity=?',(identity,)).fetchone()
            if row:binding=json.loads(row[0])
        p=json.loads(raw)
        if binding:
            parent=binding['parent'];quantity=decimal(parent['quantity']);filled=Decimal(0)
            bound_facts=[json.loads(row[0]) for row in connection.execute('SELECT raw_json FROM executions WHERE account=? AND perm_id=?',(parent['account'],parent['perm_id']))]
            from .execution_identity import correction_markers
            if correction_markers(bound_facts):raise PermissionError('Bound execution corrections require reconciliation')
            for execution in bound_facts:
                if any(execution.get(k)!=parent.get(k) for k in ('account','symbol','currency','sec_type','con_id','order_ref')) or execution.get('side') not in ('BUY','BOT'):
                    raise PermissionError('Bound daily execution identity requires reconciliation')
                shares=decimal(execution['shares'])
                if shares<=0:raise PermissionError('Bound daily fill must be positive')
                filled+=shares
            if not 0<=filled<=quantity:raise PermissionError('Bound daily fills exceed intended quantity; reconcile corrections')
            claim=connection.execute('SELECT state FROM entry_cash_claims WHERE identity=?',(identity,)).fetchone()
            # These states require terminal native proof and a later cash read.
            terminal=claim and claim[0] in ('RELEASED_TO_BROKER_CASHBOOK','BROKER_ACCOUNTED_FEE_HELD')
            amount=Decimal(0) if terminal else (quantity-filled)*decimal(parent['limit_price'])
        else:
            instant=datetime.fromisoformat(created)
            if instant.tzinfo is None:raise PermissionError('Daily request timestamp requires timezone')
            if not start<=instant<end:continue
            started=connection.execute("SELECT 1 FROM order_events WHERE idempotency_key=? AND event_type='TRANSPORT_STARTED' LIMIT 1",(identity,)).fetchone()
            if status=='REJECTED_NOT_SENT' or (status=='FAILED' and not started):continue
            # ACK without native binding is still an outstanding promise, never a fill.
            amount=decimal(p['quantity'])*decimal(p['limit_price'])
        if amount<0:raise PermissionError('Negative daily commitment is invalid')
        commitments+=amount
    facts['outstanding_commitments']=str(commitments)
    facts['entry_budget_used']=str(decimal(facts['gross_notional'])+commitments)
    return facts
