"""Broker-derived multi-currency facts. Amounts retain units; no FX orders here.

Design references: QuantConnect CashBook and Canary cash/FX evidence contracts.
This adapter does not import their strategy permissions or fabricate balances.
"""
from decimal import Decimal, InvalidOperation
import math


def convert_reference(book, amount, source_currency, target_currency, *, now, max_age_seconds=60):
    """CashBook-style accounting conversion, never an executable FX quote."""
    from datetime import datetime
    if (book.get('source') != 'BROKER_API' or book.get('account') != 'DUQ503649'
            or not 0 < max_age_seconds <= 300):
        raise PermissionError('Exact broker cashbook and bounded freshness required')
    at = datetime.fromisoformat(book['observed_at'])
    if at.tzinfo is None or not 0 <= now - at.timestamp() <= max_age_seconds:
        raise PermissionError('Currency conversion reference is stale or future')
    if isinstance(amount, bool): raise ValueError('Numeric amount required')
    value = Decimal(str(amount))
    if not value.is_finite() or value < 0: raise ValueError('Finite nonnegative amount required')
    def rate(currency):
        if not isinstance(currency, str) or len(currency) != 3: raise ValueError('Currency code required')
        if currency == book.get('base_currency'): return Decimal(1)
        row = book['currencies'][currency]
        if row.get('currency') != currency: raise ValueError('Currency identity mismatch')
        result = Decimal(str(row['rate_to_base']))
        if not result.is_finite() or result <= 0: raise ValueError('Positive finite conversion rate required')
        return result
    conversion = rate(source_currency) / rate(target_currency)
    converted = value * conversion
    if not converted.is_finite(): raise ValueError('Conversion overflow')
    return dict(amount=str(value), currency=source_currency, converted_amount=str(converted),
                target_currency=target_currency, rate=str(conversion), observed_at=book['observed_at'],
                purpose='ACCOUNTING_REFERENCE_ONLY', executable_fx_quote=False,
                grants_trading_permission=False)

PAPER_FINANCING = 'PAPER_ONLY_MAX_200USD_NEW_EXPOSURE'


def normalized_tag(tag):
    return tag.removeprefix('$LEDGER-')


def cashbook(values, account):
    fields={}
    for value in values:
        if value.account != account:continue
        tag=normalized_tag(value.tag)
        if tag not in ('CashBalance','ExchangeRate','AvailableFunds','TotalCashValue','NetLiquidation'):continue
        key=(tag,value.currency)
        try:amount=Decimal(str(value.value))
        except InvalidOperation:raise ValueError('Broker monetary field is not numeric')
        if not amount.is_finite():raise ValueError('Broker monetary field is not finite')
        if key in fields and fields[key]!=amount:raise ValueError('Conflicting monetary evidence')
        fields[key]=amount
    fund_rows=[(currency,value) for (tag,currency),value in fields.items() if tag=='AvailableFunds' and currency!='BASE']
    if len(fund_rows)!=1:raise ValueError('Unique broker account currency/funds required')
    base,funds=fund_rows[0]
    currencies={currency for (tag,currency) in fields if tag=='CashBalance' and len(currency)==3}
    rows={}
    for currency in currencies:
        rate=Decimal(1) if currency==base else fields.get(('ExchangeRate',currency))
        if rate is not None and rate<=0:raise ValueError('Invalid FX rate')
        amount=fields[('CashBalance',currency)]
        rows[currency]=dict(amount=str(amount),currency=currency,rate_to_base=str(rate) if rate is not None else None,
                            value_in_base=str(amount*rate) if rate is not None else None,
                            liability=amount<0,source='IBKR accountSummary/$LEDGER')
    return dict(account=account,base_currency=base,available_funds=str(funds),
                total_cash_value=str(fields[('TotalCashValue',base)]) if ('TotalCashValue',base) in fields else None,
                currencies=rows,source='BROKER_API',grants_trading_permission=False)


def paper_funding(book, policy='CASH_ONLY'):
    if book['source']!='BROKER_API' or not book['account'].startswith('DU'):
        raise PermissionError('Actual Paper cashbook required')
    usd=book['currencies'].get('USD')
    if usd is None:raise PermissionError('Actual USD balance missing; never assume zero')
    cash=Decimal(usd['amount']);funds=Decimal(book['available_funds'])
    base=book['base_currency']
    if base=='USD':rate=Decimal(1)
    elif usd['rate_to_base'] is not None:rate=Decimal(usd['rate_to_base'])
    else:raise PermissionError('Broker USD-to-base FX rate missing')
    capacity=cash
    mode='USD_CASH_ONLY'
    if policy==PAPER_FINANCING:
        if book['total_cash_value'] is None:raise PermissionError('Broker base cash missing')
        capacity=min(Decimal(book['total_cash_value']),funds)/rate
        mode='FINITE_PAPER_BASE_CURRENCY_CAPACITY'
    elif policy!='CASH_ONLY':raise PermissionError('Unknown financing policy')
    if not all(x.is_finite() for x in (cash,funds,capacity,rate)) or rate<=0:
        raise PermissionError('Finite verified funding evidence required')
    return dict(usd_cash=float(cash),capacity_usd=float(capacity),available_funds_usd=float(funds/rate),
                funding_mode=mode,base_currency=base,usd_to_base_rate=str(rate),
                existing_usd_borrowing=float(max(Decimal(0),-cash)),
                max_new_test_exposure_usd=200 if policy==PAPER_FINANCING else None,
                automatic_fx_conversion_performed=False)


async def fetch_paper_cashbook(ib, account):
    """Verify USD and base-currency cash through explicit ledger end markers.

    Default $LEDGER:ALL can omit currency cash rows. Never infer EUR cash
    from base-denominated net cash or available funds. Caller owns the client.
    """
    import asyncio
    from datetime import datetime,timezone
    read_started=datetime.now(timezone.utc).isoformat()
    ledger_evidence=[]
    if ib.managedAccounts() != [account]:
        raise PermissionError('Exact account required before monetary request')
    await asyncio.wait_for(ib.accountSummaryAsync(account),8)
    requested=[]
    async def ledger(currency):
        request_id=ib.client.getReqId()
        future=ib.wrapper.startReq(request_id)
        started=datetime.now(timezone.utc).isoformat()
        try:
            ib.client.reqAccountSummary(request_id,'All','$LEDGER:'+currency)
            await asyncio.wait_for(future,8)
            requested.append(currency)
            ledger_evidence.append(dict(currency=currency,request_id=request_id,started_at=started,ended_at=datetime.now(timezone.utc).isoformat()))
        finally:
            if ib.isConnected():ib.client.cancelAccountSummary(request_id)
    await ledger('USD')
    book=cashbook(list(ib.wrapper.acctSummary.values()),account)
    base=book['base_currency']
    # A cached base row may predate an FX fill. Its presence is not freshness;
    # every call must obtain a new base ledger end as well as the USD end.
    if base!='USD':await ledger(base)
    book=cashbook(list(ib.wrapper.acctSummary.values()),account)
    if 'USD' not in book['currencies'] or base not in book['currencies']:
        raise PermissionError('Broker USD and base cash rows required; missing is not zero')
    book.update(requested_currencies=requested,currency_coverage='USD_AND_BASE_VERIFIED',
                cash_read_started_at=read_started,cash_read_finished_at=datetime.now(timezone.utc).isoformat(),ledger_evidence=ledger_evidence)
    return book
