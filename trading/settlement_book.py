"""Pure native per-currency settlement facts. No generic T+n or permission inference."""
from datetime import date,datetime
from decimal import Decimal
from .instrument_facts import FIAT_CODES


def schedule(value):
    if not isinstance(value,str) or not value or len(value)>5000:raise ValueError('Bounded native settlement schedule required')
    result={}
    pieces=value.split(';')
    if len(pieces)>32:raise ValueError('Bounded settlement date count required')
    for piece in pieces:
        day,separator,amount=piece.partition(':')
        if not separator or len(day)!=8 or not day.isascii() or not day.isdecimal():raise ValueError('Explicit YYYYMMDD settlement date required')
        key=datetime.strptime(day,'%Y%m%d').date().isoformat()
        number=Decimal(amount)
        if not number.is_finite() or abs(number)>Decimal('1e100'):raise ValueError('Finite settlement amount required')
        if key in result:raise ValueError('Duplicate native settlement date')
        result[key]=str(number)
    return dict(sorted(result.items()))


def settlement_book(receipt,*,account,base_currency,as_of_day):
    """Parse only complete, exact, explicitly dated native account-update evidence.

    BASE is an accounting projection, never extra EUR/USD spendable cash. Values
    for future dates are cumulative, not independent cash inflows to add together.
    """
    if date.fromisoformat(as_of_day).isoformat()!=as_of_day:raise ValueError('Canonical YYYY-MM-DD as-of date required')
    if base_currency not in FIAT_CODES:raise ValueError('Explicit base currency required')
    if (receipt.get('source')!='NATIVE_ACCOUNT_UPDATE_MULTI' or receipt.get('account')!=account
        or receipt.get('complete') is not True or type(receipt.get('request_id')) is not int
        or receipt['request_id']<0):raise PermissionError('Exact completed native settlement request required')
    started=datetime.fromisoformat(receipt['started_at']);ended=datetime.fromisoformat(receipt['finished_at'])
    if not started.tzinfo or not ended.tzinfo or ended<started:raise ValueError('Ordered aware settlement read markers required')
    rows=receipt.get('values')
    if not isinstance(rows,list) or len(rows)>2000:raise ValueError('Bounded native settlement values required')
    found={};ready=[];projections={}
    for row in rows:
        if row.get('account')!=account or row.get('model','')!='':raise PermissionError('Mixed account or model settlement facts')
        key=row.get('key')
        if key=='AccountReady':ready.append(row.get('value'))
        if key not in ('SettledCashByDate','SettledCashByDate-S'):continue
        currency=row.get('currency')
        if currency not in FIAT_CODES and currency!='BASE':raise ValueError('Explicit native settlement currency required')
        parsed=schedule(row.get('value'));target=projections if currency=='BASE' else found
        identity=(key,currency)
        if identity in target and target[identity]!=parsed:raise ValueError('Conflicting native settlement facts')
        target[identity]=parsed
    if not ready or any(value!='true' for value in ready):raise PermissionError('Native account is not explicitly ready')
    currencies={}
    for currency in {'USD',base_currency}:
        total=found.get(('SettledCashByDate',currency))
        if total is None:raise PermissionError('Explicit USD and base settlement rows required; aggregate BASE is insufficient')
        applicable=[day for day in total if day<=as_of_day]
        effective=max(applicable) if applicable else None
        currencies[currency]={'currency':currency,'dated_cumulative_amounts':total,
            'as_of_amount':total[effective] if effective else None,'effective_date':effective,
            'securities_segment':found.get(('SettledCashByDate-S',currency))}
    return {'source':'NATIVE_ACCOUNT_UPDATE_MULTI','account':account,'base_currency':base_currency,
            'as_of_day':as_of_day,'started_at':receipt['started_at'],'finished_at':receipt['finished_at'],
            'request_id':receipt['request_id'],'currencies':currencies,
            'base_projections':{key:s for (key,_),s in projections.items()},
            'future_values_are_cumulative':True,'grants_execution_permission':False,
            'stock_value_date_verified':False}
