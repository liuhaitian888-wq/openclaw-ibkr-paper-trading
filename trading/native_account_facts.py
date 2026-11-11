"""Typed account facts from one existing native owner, never trading authority."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from zoneinfo import ZoneInfo
from .entry_admission import aware_stamp
from .settlement_book import settlement_book

ACCOUNT = 'DUQ503649'
FIELDS = {'NetLiquidation': 'net_liquidation', 'TotalCashValue': 'total_cash_value',
          'AvailableFunds': 'available_funds', 'BuyingPower': 'buying_power'}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Explicit native monetary number required')
    number = Decimal(str(value))
    if not number.is_finite() or abs(number) > Decimal('1e100'):
        raise ValueError('Native monetary number unavailable')
    return str(number)


def transport_facts(book, state, *, now):
    """Authenticated native callback path, independent of public TLS egress."""
    generation=state.get('api_protocol',{}).get('connection');epoch=state.get('epoch')
    if (not isinstance(generation,str) or not generation or not isinstance(epoch,str) or not epoch
            or any(state.get(k) is not True for k in ('connected','identity','upstream_connected'))
            or not 0<=now-state.get('last_server_reply',0)<=10):
        raise PermissionError('Current exact authenticated native session required')
    server=state.get('native_server_clock',{})
    if (server.get('valid') is not True or server.get('connection_generation')!=generation
            or type(server.get('timestamp')) is not int or not 0<=now-server.get('received_at',0)<=10
            or abs(server['received_at']-server['timestamp'])>10):
        raise PermissionError('Current native server clock required')
    start=aware_stamp(book['cash_read_started_at']);end=aware_stamp(book['cash_read_finished_at'])
    receipt=book['settlement_receipt']
    if (book.get('source')!='BROKER_API' or book.get('account')!=ACCOUNT
            or book.get('grants_trading_permission') is not False
            or book.get('connection_generation')!=generation or book.get('broker_epoch')!=epoch
            or not 0<=now-end<=10 or not start<=end<=now or aware_stamp(book['observed_at'])!=end
            or aware_stamp(receipt['started_at'])!=start or aware_stamp(receipt['finished_at'])!=end
            or receipt.get('connection_generation')!=generation):
        raise PermissionError('Current exact native ledger receipt required')
    payload=json.dumps(book,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
    status=state.get('currency_book_status',{})
    if (len(payload)>100000 or status.get('sha256')!=hashlib.sha256(payload).hexdigest()
            or status.get('request_id')!=receipt.get('request_id')
            or status.get('connection_generation')!=generation):
        raise PermissionError('Owned cashbook publication fingerprint required')
    settlement=settlement_book(receipt,account=ACCOUNT,base_currency=book['base_currency'],
        as_of_day=datetime.fromtimestamp(now,ZoneInfo('America/New_York')).date().isoformat())
    return dict(account=ACCOUNT,environment='PAPER',source='NATIVE_CALLBACK_OWNER',
        broker_epoch=epoch,connection_generation=generation,server_clock=server,
        ledger_request_id=receipt['request_id'],ledger_observed_at=receipt['finished_at'],
        settlement=settlement,grants_trading_permission=False)


def account_facts(book, state, *, now, pnl_publication_blocked):
    """Receipt freshness is distinct from economic posting or tick freshness."""
    if state.get('local_persistence_failure'):
        raise PermissionError('Local native snapshot persistence requires reconciliation')
    if pnl_publication_blocked is not False:
        raise PermissionError('PnL publication failure must be reconciled locally')
    transport=transport_facts(book,state,now=now)
    generation=transport['connection_generation'];epoch=transport['broker_epoch'];server=transport['server_clock']
    start=aware_stamp(book['cash_read_started_at']);receipt=book['settlement_receipt']
    if (state.get('dirty') is not False
            or set(state.get('ends',[]))!={'positions','orders','completed_orders','executions'}
            or not 0<=now-state.get('reconciled_at',0)<=30
            or book.get('broker_reconciled_at')!=state['reconciled_at']
            or start<max(state['reconciled_at'],state.get('latest_cash_change_at',0))):
        raise PermissionError('Fresh exact native account reconciliation required')
    base = book['base_currency']
    settlement = transport['settlement']
    rows = receipt['values']
    if len(rows) > 128:
        raise ValueError('Bounded native account receipt required')
    account = {}
    for row in rows:
        tag = row.get('key')
        if tag not in FIELDS or row.get('currency') != base:
            continue
        name = FIELDS[tag]
        if name in account:
            raise ValueError('Unique native account monetary field required')
        account[name] = dict(value=finite(row.get('value')), currency=base,
            source='NATIVE_ACCOUNT_UPDATE_MULTI', received_at=receipt['finished_at'])
    if set(account) != set(FIELDS.values()):
        raise ValueError('Complete explicitly denominated native account fields required')
    pnl = state.get('native_pnl', {})
    if (pnl.get('account') != ACCOUNT or pnl.get('source') != 'NATIVE_ACCOUNT_PNL'
            or pnl.get('grants_trading_permission') is not False
            or pnl.get('connection_generation') != generation or pnl.get('broker_epoch') != epoch
            or pnl.get('admission_generation') != epoch
            or not state['reconciled_at'] <= aware_stamp(pnl['started_at']) <= aware_stamp(pnl['observed_at']) <= now
            or not 0 <= now-aware_stamp(pnl['observed_at']) <= 35):
        raise PermissionError('Fresh owned account PnL evidence required')
    pnl = {**pnl, **{key: finite(pnl.get(key)) for key in ('daily', 'unrealized', 'realized')},
        'currency': None, 'currency_status': 'NOT_IN_NATIVE_CALLBACK',
        'usable_for_monetary_limits': False}
    return dict(account_id=ACCOUNT, environment='PAPER', source='NATIVE_ACCOUNT_OWNER',
        broker_epoch=epoch, connection_generation=generation, account=account, pnl=pnl,
        base_currency=base, settlement=settlement, server_clock=server,
        cash_read_started_at=receipt['started_at'], cash_read_finished_at=receipt['finished_at'],
        receipt_freshness_is_not_economic_posting_proof=True, grants_trading_permission=False)
