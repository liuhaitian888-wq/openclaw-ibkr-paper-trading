"""Transaction-local stock-entry resource claims; never owns a broker transport."""
from datetime import datetime,time,timedelta,timezone
from decimal import Decimal
import hashlib
import json
from zoneinfo import ZoneInfo


def decimal(value):
    if isinstance(value,bool):raise ValueError('Boolean is not a monetary amount')
    amount=Decimal(str(value))
    if not amount.is_finite():raise ValueError('Finite monetary amount required')
    return amount


def aware_stamp(value):
    at=datetime.fromisoformat(value)
    if at.tzinfo is None:raise ValueError('Timezone-aware native proof timestamp required')
    return at.timestamp()


def enforce_daily_budget(connection,proposal,cap,timezone_name,created_at):
    cap=decimal(cap)
    if cap<=0:raise PermissionError('Positive daily notional cap required')
    zone=ZoneInfo(timezone_name);at=datetime.fromisoformat(created_at);day=at.astimezone(zone).date()
    from .daily_turnover import admission_usage
    used=decimal(admission_usage(connection,day.isoformat(),timezone_name)['entry_budget_used'])
    proposed=decimal(proposal.quantity)*decimal(proposal.limit_price)
    if proposed<=0 or used+proposed>cap:
        raise PermissionError(f'Daily notional cap exceeded: used={used}, proposed={proposed}, cap={cap}, timezone={timezone_name}')


def initialize_claims(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS entry_cash_claims(
        identity TEXT PRIMARY KEY,account TEXT NOT NULL,state TEXT NOT NULL,
        reserved_usd TEXT NOT NULL,fee_usd TEXT NOT NULL,created_at TEXT NOT NULL,
        cash_observed_at TEXT NOT NULL,broker_epoch TEXT NOT NULL,
        evidence TEXT NOT NULL)''')
    connection.execute('CREATE INDEX IF NOT EXISTS entry_cash_claim_state ON entry_cash_claims(state)')
    connection.execute('''CREATE TABLE IF NOT EXISTS entry_native_bindings(
        identity TEXT PRIMARY KEY,perm_id INTEGER NOT NULL UNIQUE,bound_at TEXT NOT NULL,
        binding TEXT NOT NULL)''')


def reserve_cash(connection,root,proposal,created_at):
    # Called only within the same BEGIN IMMEDIATE as the durable order intent.
    from .cash_guard import enforce
    context=enforce(root,proposal)
    if context is None:return # Legacy non-funded environments retain their explicit policy.
    initialize_claims(connection)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_fee_facts'").fetchone():
        latest=connection.execute("SELECT max(updated_at) FROM execution_fee_facts WHERE account='DUQ503649'").fetchone()[0]
        if latest:
            try:ordered=aware_stamp(context['cashbook'].get('cash_read_started_at'))>=aware_stamp(latest)
            except (ValueError,TypeError):ordered=False
            if not ordered:raise PermissionError('Cash ledger read predates a known fee revision or lacks its start marker')
    if not context['broker_epoch']:raise PermissionError('Cash reservation requires a broker reconciliation epoch')
    # All external currency/unsupported orders still consume uncertainty even if additive caps are blank.
    for order in context['broker_state'].get('orders',{}).values():
        if order.get('completed') or order.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive'):continue
        if order.get('account')!='DUQ503649' or order.get('sec_type')!='STK' or order.get('currency')!='USD':
            raise PermissionError('Non-stock or unknown active order requires account risk reconciliation')
    uncertain=connection.execute("SELECT 1 FROM entry_cash_claims c JOIN order_requests r ON r.idempotency_key=c.identity WHERE c.identity!=? AND (c.state IN ('STARTED','UNKNOWN') OR r.status IN ('UNKNOWN','PAPER_PENDING_CONFIRMATION','PAPER_LIMIT_PENDING_CONFIRMATION')) LIMIT 1",(proposal.idempotency_key,)).fetchone()
    if uncertain:raise PermissionError('Prior entry submission is reserved/started/unknown; exact reconciliation required')
    reconcile_cash_claims(connection,context,created_at)
    pending=Decimal(0)
    for state,amount in connection.execute("SELECT state,reserved_usd FROM entry_cash_claims WHERE state NOT IN ('RELEASED_TO_BROKER_CASHBOOK','RELEASED_NOT_SENT')"):
        if state=='UNKNOWN':raise PermissionError('Unknown prior entry cash claim requires exact reconciliation')
        if state not in ('RESERVED','STARTED','ACKNOWLEDGED_UNRECONCILED','TRANSFERRED_TO_BROKER_ORDER','BROKER_ACCOUNTED_FEE_HELD'):raise PermissionError('Unrecognized cash claim state')
        if decimal(amount)<0:raise PermissionError('Negative cash reservation is invalid')
        pending+=decimal(amount)
    available=decimal(context['cash_usd'])-decimal(context['external_reserved_usd'])-pending
    cost=decimal(context['cost_usd'])
    if available<cost:raise PermissionError('USD cash already reserved by another entry intent; no new borrowing allowed')
    # Until an exact native binding is reconciled, keeping a claim can be conservative.
    # Do not deduplicate by a look-alike orderRef or drop a claim merely on ACK/FAILED.
    evidence={k:v for k,v in context.items() if k not in ('broker_state','cashbook')}
    evidence['snapshot_sha256']=hashlib.sha256(json.dumps(context['broker_state'],sort_keys=True).encode()).hexdigest()
    evidence['cashbook_sha256']=hashlib.sha256(json.dumps(context['cashbook'],sort_keys=True).encode()).hexdigest()
    connection.execute("INSERT INTO entry_cash_claims VALUES(?,?,'RESERVED',?,?,?,?,?,?)",(proposal.idempotency_key,'DUQ503649',str(cost),context['fee_reserve_usd'],created_at,context['cash_observed_at'],context['broker_epoch'],json.dumps(evidence,sort_keys=True)))


def bind_submission(connection,identity,order_ids,broker_orders,expected_client_id,at):
    """Only evidence captured by this submission's native callback can establish this binding.

    This grants no cancellation, adoption or strategy mutation authority.
    """
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='entry_cash_claims'").fetchone():return None
    claim=connection.execute('SELECT state FROM entry_cash_claims WHERE identity=?',(identity,)).fetchone()
    if not claim:return None
    initialize_claims(connection)
    row=connection.execute('SELECT proposal_json FROM order_requests WHERE idempotency_key=?',(identity,)).fetchone()
    p=json.loads(row[0]);parent_id=order_ids[0] if order_ids else None
    def valid_integer(v):return type(v) is int and v>0
    try:
        records={int(k):dict(v) for k,v in (broker_orders or {}).items()}
        parent=records[parent_id]
        if (parent.get('account')!='DUQ503649' or parent.get('sec_type')!='STK' or parent.get('currency')!='USD'
            or parent.get('client_id')!=expected_client_id or type(expected_client_id) is not int or expected_client_id<0
            or not valid_integer(parent.get('perm_id')) or not valid_integer(parent.get('con_id'))
            or parent.get('symbol')!=p['symbol'] or parent.get('side')!=p['side'] or p['side']!='BUY'
            or parent.get('order_id')!=parent_id or parent.get('parent_id',0)!=0
            or parent.get('order_ref')!=identity or parent.get('order_type')!='LMT'
            or decimal(parent.get('quantity'))!=decimal(p['quantity'])
            or not 0<decimal(parent.get('limit_price'))<=decimal(p['limit_price'])):
            raise ValueError('Exact native parent identity/economics missing')
        for order_id in order_ids:
            order=records[order_id]
            if (order.get('order_id')!=order_id or order.get('account')!=parent['account']
                or order.get('client_id')!=expected_client_id or order.get('con_id')!=parent['con_id']
                or order.get('sec_type')!='STK' or order.get('currency')!='USD'
                or order.get('symbol')!=p['symbol'] or order.get('order_ref')!=identity
                or not valid_integer(order.get('perm_id'))):raise ValueError('Incomplete linked native identity')
            if order_id!=parent_id and (order.get('parent_id')!=parent_id or order.get('side')!='SELL'
                    or order.get('order_type')!='STP' or decimal(order.get('quantity'))!=decimal(p['quantity'])):
                raise ValueError('Linked stop identity differs')
        if len({records[k]['perm_id'] for k in order_ids})!=len(order_ids):raise ValueError('Duplicate native permId')
        fields=('order_id','perm_id','parent_id','client_id','account','symbol','con_id','sec_type','currency','side','order_type','quantity','limit_price','aux_price','tif','order_ref')
        fixed=lambda order:{k:order.get(k) for k in fields}
        binding={'identity':identity,'parent':fixed(parent),'linked_orders':[fixed(records[k]) for k in order_ids],
                 'source':'DIRECT_SUBMISSION_NATIVE_CALLBACK','mutation_authorized':False}
        prior=connection.execute('SELECT binding FROM entry_native_bindings WHERE identity=?',(identity,)).fetchone()
        if prior and json.loads(prior[0])!=binding:raise ValueError('Binding cannot change')
        other=connection.execute('SELECT identity FROM entry_native_bindings WHERE perm_id=?',(parent['perm_id'],)).fetchone()
        if other and other[0]!=identity:raise ValueError('Native identity belongs to another intent')
        connection.execute('INSERT OR IGNORE INTO entry_native_bindings VALUES(?,?,?,?)',(identity,parent['perm_id'],at,json.dumps(binding,sort_keys=True)))
        return True
    except (ValueError,TypeError,KeyError,ArithmeticError):
        connection.execute("UPDATE entry_cash_claims SET state='UNKNOWN' WHERE identity=?",(identity,))
        return False


def reconcile_cash_claims(connection,context,at):
    """Read-only native proof transfers claims; this function never replays a broker action."""
    state=context['broker_state'];book=context['cashbook']
    try:
        observed=aware_stamp(at)
        if (book.get('source')!='BROKER_API' or book.get('account')!='DUQ503649'
            or state.get('identity') is not True or state.get('connected') is not True
            or state.get('upstream_connected') is not True or state.get('dirty') is not False
            or set(state.get('ends',[]))!={'positions','orders','completed_orders','executions'}
            or not 0<=decimal(observed)-decimal(state.get('last_server_reply'))<=10):return
        if not 0<=observed-aware_stamp(book['observed_at'])<=10:return
        started=datetime.fromisoformat(book['cash_read_started_at'])
        finished=datetime.fromisoformat(book['cash_read_finished_at'])
        if not started.tzinfo or not finished.tzinfo or started>finished or finished.timestamp()>aware_stamp(book['observed_at']): return
        if book.get('currency_coverage')!='USD_AND_BASE_VERIFIED':return
        currencies=set(book.get('requested_currencies',[]))
        if 'USD' not in currencies or book.get('base_currency') not in currencies:return
        if not state.get('reconciled_at') or started.timestamp()<state['reconciled_at']:return
    except (KeyError,ValueError,TypeError,ArithmeticError):return
    rows=connection.execute("SELECT c.identity,c.state,c.reserved_usd,c.fee_usd,b.bound_at,b.binding FROM entry_cash_claims c JOIN entry_native_bindings b ON c.identity=b.identity WHERE c.state IN ('ACKNOWLEDGED_UNRECONCILED','TRANSFERRED_TO_BROKER_ORDER','BROKER_ACCOUNTED_FEE_HELD')").fetchall()
    for identity,claim_state,prior_amount,fee,bound_at,raw in rows:
        binding=json.loads(raw);parent=binding['parent'];perm=parent['perm_id']
        if state['reconciled_at']<aware_stamp(bound_at):continue
        matches=[o for o in state.get('orders',{}).values() if o.get('perm_id')==perm and o.get('account')==parent['account']]
        if len(matches)!=1:continue
        native=matches[0]
        fixed=('account','con_id','symbol','currency','sec_type','side','order_type','quantity','limit_price','order_ref')
        if any(native.get(k)!=parent.get(k) for k in fixed):continue
        if native.get('client_id')!=parent['client_id'] and not (native.get('completed') and native.get('client_id')==0):continue
        try:
            filled=decimal(native.get('filled'));remaining=decimal(native.get('remaining'))
            if filled<0 or remaining<0 or filled+remaining>decimal(parent['quantity']):continue
            terminal=native.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive')
            if not terminal and native.get('status') not in ('Submitted','PreSubmitted'):continue
            if native.get('status')=='Filled' and (remaining or filled!=decimal(parent['quantity'])):continue
            if terminal and remaining and native.get('status')=='Filled':continue
            executions=[]
            for row in connection.execute('SELECT raw_json,first_seen_at FROM executions WHERE account=? AND perm_id=?',(parent['account'],perm)):
                execution=json.loads(row[0])
                if any(execution.get(k)!=parent.get(k) for k in ('account','symbol','currency','sec_type','con_id','order_ref')):raise ValueError('Execution contract differs')
                if execution.get('side') not in ('BUY','BOT'):raise ValueError('Execution side differs')
                if aware_stamp(row[1])>started.timestamp():raise ValueError('Ledger read predates execution receipt')
                if decimal(execution['shares'])<=0 or not 0<decimal(execution['price'])<=decimal(parent['limit_price']):raise ValueError('Unsupported execution economics')
                executions.append(execution)
            if sum((decimal(e['shares']) for e in executions),Decimal(0))!=filled:continue
            if not terminal:
                # Exact active parent is already reserved by cash_guard's broker-order calculation.
                amount=Decimal(0);new_state='TRANSFERRED_TO_BROKER_ORDER'
            else:
                amount=decimal(fee) if filled else Decimal(0)
                actual_fees=True
                for execution in executions:
                    record=connection.execute('SELECT currency,amount,account,updated_at FROM execution_fee_facts WHERE exec_id=?',(execution['exec_id'],)).fetchone()
                    if not record or record[2]!=parent['account'] or record[0] not in currencies or aware_stamp(record[3])>started.timestamp():
                        actual_fees=False;break
                    cash_row=book['currencies'].get(record[0])
                    if not cash_row or cash_row.get('currency')!=record[0] or decimal(cash_row['amount'])<0:actual_fees=False;break
                if actual_fees:amount=Decimal(0)
                new_state='BROKER_ACCOUNTED_FEE_HELD' if amount else 'RELEASED_TO_BROKER_CASHBOOK'
            if amount<0:continue
            if new_state!=claim_state or amount!=decimal(prior_amount):
                connection.execute('UPDATE entry_cash_claims SET state=?,reserved_usd=? WHERE identity=?',(new_state,str(amount),identity))
                proof={'identity':identity,'native_perm_id':perm,'state':new_state,'reserved_usd':str(amount),'cash_read_started_at':book['cash_read_started_at'],'broker_epoch':state['epoch'],'cashbook':book,'source':'EXACT_NATIVE_ACCOUNTING_RECONCILIATION','mutation_authorized':False}
                connection.execute('INSERT INTO order_events(idempotency_key,occurred_at,event_type,status,details) VALUES(?,?,?,?,?)',(identity,at,'CASH_CLAIM_RECONCILED',new_state,json.dumps(proof,sort_keys=True)))
        except (ValueError,TypeError,KeyError,ArithmeticError):continue
