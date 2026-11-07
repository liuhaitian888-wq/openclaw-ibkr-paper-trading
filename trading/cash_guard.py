"""Owner-required cash-only boundary. Missing/stale funding evidence rejects orders."""
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import json,time
from reporting.database_console import contained


def enforce(root,proposal,*,now=None):
    root=Path(root)
    if not (root/'runtime/FUNDING_POLICY_REQUIRED').exists() and not (root/'runtime/funding-policy.json').exists():return
    now=time.time() if now is None else now
    try:
        def load(name):
            p=contained(root,name)
            if p.stat().st_size>100000:raise ValueError('Bounded funding document required')
            return json.loads(p.read_text())
        policy=load('runtime/funding-policy.json')
        if not (policy.get('approved') is True and policy.get('account')=='DUQ503649' and policy.get('environment')=='PAPER'
                and policy.get('mode')=='CASH_ONLY_NO_NEW_BORROWING' and policy.get('allow_new_currency_debit') is False):
            raise ValueError('Approved cash-only funding boundary required')
        # A SELL proposal is not proof of a risk-reducing close. The owned exit path must verify it separately.
        if proposal.side!='BUY':raise ValueError('Cash-only entry path forbids short sales; verified owned exit required')
        book=load('runtime/currency-book.latest.json')
        at=datetime.fromisoformat(book['observed_at'])
        if at.tzinfo is None or not 0<=now-at.timestamp()<=10:raise ValueError('Fresh currency cashbook <=10s required')
        if book.get('source')!='BROKER_API' or book.get('account')!='DUQ503649':raise ValueError('Exact broker funding identity required')
        cash=Decimal(book['currencies']['USD']['amount']);fee=Decimal(str(policy.get('fee_reserve_usd')))
        if not cash.is_finite() or not fee.is_finite() or fee<=0:raise ValueError('Explicit positive fee/FX reserve required; missing fees are not zero')
        # Reserve every active external BUY, not just local strategy intents. Unknown pricing blocks.
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(contained(root,'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
            c.execute('PRAGMA query_only=ON');deadline=time.monotonic()+.2;c.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
            state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
        if not (state.get('identity') is True and state.get('connected') is True and state.get('dirty') is False and state.get('upstream_connected') is True
                and set(state.get('ends',[]))=={'positions','orders','completed_orders','executions'} and 0<=now-state.get('last_server_reply',0)<=10):raise ValueError('Fresh complete broker reservations required')
        reserved=Decimal(0)
        for order in state.get('orders',{}).values():
            if order.get('completed') or order.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive'):continue
            if order.get('side')!='BUY':continue
            if order.get('account')!='DUQ503649' or order.get('currency')!='USD' or order.get('order_type')!='LMT':raise ValueError('Unbounded active buy reservation')
            qty=Decimal(str(order['remaining']));price=Decimal(str(order['limit_price']))
            if not qty.is_finite() or not price.is_finite() or qty<0 or price<=0:raise ValueError('Invalid active buy reservation')
            reserved+=qty*price+fee
        cost=Decimal(proposal.quantity)*Decimal(str(proposal.limit_price))+fee
        if not cost.is_finite() or cost<=0 or cash-reserved<cost:raise ValueError('USD cash cannot cover entry, all active buys and fee reserve; no new borrowing allowed')
    except Exception as exc:
        raise PermissionError('Cash-only gate blocked: '+str(exc)) from exc
