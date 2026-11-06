"""Broker-derived multi-currency facts. Amounts retain units; no FX orders here.

Design references: QuantConnect CashBook and Canary cash/FX evidence contracts.
This adapter does not import their strategy permissions or fabricate balances.
"""
from decimal import Decimal, InvalidOperation
import math

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
    """Own one explicit USD-ledger request through its end marker and cancellation.

    ib_async 2.1.0's default $LEDGER:ALL request can return only base summary
    fields. An explicit USD request is required; never synthesize a USD row.
    The caller owns the connected client and its bounded lifetime.
    """
    import asyncio
    if ib.managedAccounts() != [account]:
        raise PermissionError('Exact account required before monetary request')
    await asyncio.wait_for(ib.accountSummaryAsync(account),8)
    request_id=ib.client.getReqId()
    future=ib.wrapper.startReq(request_id)
    try:
        ib.client.reqAccountSummary(request_id,'All','$LEDGER:USD')
        await asyncio.wait_for(future,8)
        return cashbook(list(ib.wrapper.acctSummary.values()),account)
    finally:
        if ib.isConnected():ib.client.cancelAccountSummary(request_id)
