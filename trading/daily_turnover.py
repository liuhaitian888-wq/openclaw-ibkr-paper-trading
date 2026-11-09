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
    rows=connection.execute('SELECT exec_id,raw_json,first_seen_at FROM executions WHERE account=? ORDER BY exec_id',(account,))
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
