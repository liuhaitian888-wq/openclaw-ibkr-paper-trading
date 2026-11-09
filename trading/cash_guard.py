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
        if book['currencies']['USD'].get('currency')!='USD':raise ValueError('Explicit USD cash unit required; never treat EUR or unitless funds as USD')
        cash=Decimal(book['currencies']['USD']['amount']);fee=Decimal(str(policy.get('fee_reserve_usd')))
        if not cash.is_finite() or not fee.is_finite() or fee<=0:raise ValueError('Explicit positive fee/FX reserve required; missing fees are not zero')
        # Trade-date cash is not proof of settled funding. Without verified stock
        # value-date matching, require current and scheduled USD capacity to cover
        # the entry and fees; an aggregate EUR/BASE balance cannot replace it.
        from .settlement_book import settlement_book
        from zoneinfo import ZoneInfo
        receipt=book['settlement_receipt']
        settlement=settlement_book(receipt,account='DUQ503649',base_currency=book['base_currency'],
                                   as_of_day=datetime.fromtimestamp(now,ZoneInfo('America/New_York')).date().isoformat())
        cash_started=datetime.fromisoformat(book['cash_read_started_at'])
        cash_finished=datetime.fromisoformat(book['cash_read_finished_at'])
        if not cash_started.tzinfo or not cash_finished.tzinfo or not cash_started<=cash_finished<=at:raise ValueError('Ordered cash read markers required')
        settled_start=datetime.fromisoformat(receipt['started_at'])
        settled_end=datetime.fromisoformat(receipt['finished_at'])
        if not (0<=now-settled_end.timestamp()<=10 and settled_end<=at):raise ValueError('Fresh ordered settlement proof <=10s required')
        usd_settlement=settlement['currencies']['USD']
        if usd_settlement['as_of_amount'] is None:raise ValueError('Current settled USD is unknown')
        scheduled=[Decimal(amount) for day,amount in usd_settlement['dated_cumulative_amounts'].items() if day>=settlement['as_of_day']]
        settled_capacity=min([Decimal(usd_settlement['as_of_amount'])]+scheduled)
        ledger_cash=cash;cash=min(cash,settled_capacity)

        # Reserve every active external BUY, not just local strategy intents. Unknown pricing blocks.
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(contained(root,'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
            c.execute('PRAGMA query_only=ON');deadline=time.monotonic()+.2;c.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
            state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
        if not (state.get('identity') is True and state.get('connected') is True and state.get('dirty') is False and state.get('upstream_connected') is True
                and set(state.get('ends',[]))=={'positions','orders','completed_orders','executions'} and 0<=now-state.get('last_server_reply',0)<=10):raise ValueError('Fresh complete broker reservations required')
        if (not state.get('epoch') or book.get('broker_epoch')!=state['epoch']
                or not book.get('connection_generation') or book['connection_generation']!=state.get('api_protocol',{}).get('connection')
                or not state.get('reconciled_at') or cash_started.timestamp()<state['reconciled_at']):
            raise ValueError('Cashbook must follow the current native epoch, connection and reconciliation')
        changed=state.get('latest_cash_change_at',0)
        if changed:
            started=datetime.fromisoformat(book['cash_read_started_at'])
            if started.tzinfo is None or started.timestamp()<changed or settled_start.timestamp()<changed:raise ValueError('Cash or settlement read predates known execution/fee update')
        reserved=Decimal(0)
        for order in state.get('orders',{}).values():
            if order.get('completed') or order.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive'):continue
            if order.get('side')!='BUY':continue
            if order.get('account')!='DUQ503649' or order.get('currency')!='USD' or order.get('order_type')!='LMT':raise ValueError('Unbounded active buy reservation')
            qty=Decimal(str(order['remaining']));price=Decimal(str(order['limit_price']))
            if not qty.is_finite() or not price.is_finite() or qty<0 or price<=0:raise ValueError('Invalid active buy reservation')
            reserved+=qty*price+fee
        if type(proposal.quantity) is not int or proposal.quantity<=0:raise ValueError('Positive whole-share cash claim quantity required')
        cost=Decimal(proposal.quantity)*Decimal(str(proposal.limit_price))+fee
        if not cost.is_finite() or cost<=0 or cash-reserved<cost:raise ValueError('USD cash cannot cover entry, all active buys and fee reserve; no new borrowing allowed')
        return dict(cash_usd=str(cash),ledger_cash_usd=str(ledger_cash),settled_capacity_usd=str(settled_capacity),external_reserved_usd=str(reserved),cost_usd=str(cost),fee_reserve_usd=str(fee),
                    cash_observed_at=book['observed_at'],cash_read_started_at=book.get('cash_read_started_at'),broker_epoch=state.get('epoch'),
                    broker_reconciled_at=state.get('reconciled_at'),broker_state=state,cashbook=book)
    except Exception as exc:
        raise PermissionError('Cash-only gate blocked: '+str(exc)) from exc
