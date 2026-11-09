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


def enforce_daily_budget(connection,proposal,cap,timezone_name,created_at):
    cap=decimal(cap)
    if cap<=0:raise PermissionError('Positive daily notional cap required')
    zone=ZoneInfo(timezone_name);at=datetime.fromisoformat(created_at);day=at.astimezone(zone).date()
    start=datetime.combine(day,time(),zone).astimezone(timezone.utc).isoformat()
    end=datetime.combine(day+timedelta(days=1),time(),zone).astimezone(timezone.utc).isoformat()
    used=Decimal(0)
    for raw, in connection.execute("SELECT proposal_json FROM order_requests WHERE created_at>=? AND created_at<? AND mode LIKE 'PAPER%' AND mode!='PAPER_CASH_CONVERSION' AND status NOT IN ('FAILED','REJECTED_NOT_SENT')",(start,end)):
        p=json.loads(raw);amount=decimal(p['quantity'])*decimal(p['limit_price'])
        if amount<0:raise PermissionError('Invalid historical daily notional')
        used+=amount
    proposed=decimal(proposal.quantity)*decimal(proposal.limit_price)
    if proposed<=0 or used+proposed>cap:
        raise PermissionError(f'Daily notional cap exceeded: used={used}, proposed={proposed}, cap={cap}, timezone={timezone_name}')


def initialize_claims(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS entry_cash_claims(
        identity TEXT PRIMARY KEY,account TEXT NOT NULL,state TEXT NOT NULL,
        reserved_usd TEXT NOT NULL,fee_usd TEXT NOT NULL,created_at TEXT NOT NULL,
        cash_observed_at TEXT NOT NULL,broker_epoch TEXT NOT NULL,
        evidence TEXT NOT NULL)''')


def reserve_cash(connection,root,proposal,created_at):
    # Called only within the same BEGIN IMMEDIATE as the durable order intent.
    from .cash_guard import enforce
    context=enforce(root,proposal)
    if context is None:return # Legacy non-funded environments retain their explicit policy.
    initialize_claims(connection)
    if not context['broker_epoch']:raise PermissionError('Cash reservation requires a broker reconciliation epoch')
    # All external currency/unsupported orders still consume uncertainty even if additive caps are blank.
    for order in context['broker_state'].get('orders',{}).values():
        if order.get('completed') or order.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive'):continue
        if order.get('account')!='DUQ503649' or order.get('sec_type')!='STK' or order.get('currency')!='USD':
            raise PermissionError('Non-stock or unknown active order requires account risk reconciliation')
    uncertain=connection.execute("SELECT 1 FROM entry_cash_claims c JOIN order_requests r ON r.idempotency_key=c.identity WHERE c.identity!=? AND (c.state IN ('STARTED','UNKNOWN') OR r.status IN ('UNKNOWN','PAPER_PENDING_CONFIRMATION','PAPER_LIMIT_PENDING_CONFIRMATION')) LIMIT 1",(proposal.idempotency_key,)).fetchone()
    if uncertain:raise PermissionError('Prior entry submission is reserved/started/unknown; exact reconciliation required')
    pending=Decimal(0)
    for state,amount in connection.execute("SELECT state,reserved_usd FROM entry_cash_claims WHERE state NOT IN ('RELEASED_TO_BROKER_CASHBOOK','RELEASED_NOT_SENT')"):
        if state=='UNKNOWN':raise PermissionError('Unknown prior entry cash claim requires exact reconciliation')
        pending+=decimal(amount)
    available=decimal(context['cash_usd'])-decimal(context['external_reserved_usd'])-pending
    cost=decimal(context['cost_usd'])
    if available<cost:raise PermissionError('USD cash already reserved by another entry intent; no new borrowing allowed')
    # Until an exact native binding is reconciled, keeping a claim can be conservative.
    # Do not deduplicate by a look-alike orderRef or drop a claim merely on ACK/FAILED.
    evidence={k:v for k,v in context.items() if k!='broker_state'}
    evidence['snapshot_sha256']=hashlib.sha256(json.dumps(context['broker_state'],sort_keys=True).encode()).hexdigest()
    connection.execute("INSERT INTO entry_cash_claims VALUES(?,?,'RESERVED',?,?,?,?,?,?)",(proposal.idempotency_key,'DUQ503649',str(cost),context['fee_reserve_usd'],created_at,context['cash_observed_at'],context['broker_epoch'],json.dumps(evidence,sort_keys=True)))
