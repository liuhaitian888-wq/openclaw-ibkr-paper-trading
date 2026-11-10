"""Pure native ladder validation; no SDK, journal, cash or trading authority.

minTick alone is insufficient. Callers must bind contract/exchange rule evidence
from their owned connection and recheck the resulting economics before wire.
"""
from decimal import Decimal, ROUND_FLOOR, localcontext
from .entry_admission import aware_stamp


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Explicit finite price required')
    out=Decimal(str(value))
    if not out.is_finite() or out.copy_abs()>Decimal('1e20') or out.as_tuple().exponent < -12:
        raise ValueError('Bounded explicit finite price required')
    return out


def ladder(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=256:
        raise ValueError('Complete bounded native price ladder required')
    result=[]
    for row in rows:
        low,tick=number(row['low_edge']),number(row['increment'])
        if low<0 or tick<=0 or (result and low<=result[-1][0]):
            raise ValueError('Native ladder must have increasing nonnegative edges and positive ticks')
        result.append((low,tick))
    if result[0][0]!=0:raise ValueError('Native ladder must cover prices from zero')
    return result


def floor_price(value, rows):
    """Round down then validate at the resulting band; never invent a tick."""
    price=number(value)
    if price<=0:raise ValueError('Positive price required')
    bands=ladder(rows)
    with localcontext() as ctx:
        ctx.prec=80
        for _ in range(len(bands)+1):
            tick=next(t for low,t in reversed(bands) if low<=price)
            candidate=(price/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
            if candidate<=0:raise ValueError('Rounding eliminated positive order price')
            actual=next(t for low,t in reversed(bands) if low<=candidate)
            if candidate%actual==0:return candidate
            price=candidate
    raise ValueError('Native ladder rounding did not converge')


def normalize_long_entry(proposal, contract, rule, *, exchange, generation, now):
    """Unprivileged calculation only; does not authenticate caller evidence."""
    if (contract.get('source')!='NATIVE_CONTRACT_DETAILS' or contract.get('complete') is not True
            or contract.get('connection_generation')!=generation or not isinstance(generation,str) or not generation
            or contract.get('sec_type')!='STK' or contract.get('currency')!='USD'
            or contract.get('symbol')!=proposal.get('symbol')
            or type(contract.get('con_id')) is not int or contract['con_id']<=0
            or not 0<=now-aware_stamp(contract['observed_at'])<=10
            or rule.get('source')!='NATIVE_MARKET_RULE' or rule.get('complete') is not True
            or rule.get('connection_generation')!=generation
            or not 0<=now-aware_stamp(rule['observed_at'])<=10):
        raise PermissionError('Exact fresh native stock contract and rule required')
    exchanges=contract.get('valid_exchanges','').split(',')
    ids=contract.get('market_rule_ids','').split(',')
    if (not isinstance(exchange,str) or not exchange or len(exchanges)!=len(ids)
            or len(exchanges)>256 or exchanges.count(exchange)!=1):
        raise PermissionError('Unambiguous native exchange/rule mapping required')
    raw=ids[exchanges.index(exchange)]
    if (not raw.isascii() or not raw.isdecimal() or int(raw)<=0
            or type(rule.get('market_rule_id')) is not int or rule['market_rule_id']!=int(raw)):
        raise PermissionError('Selected native exchange rule differs or is unavailable')
    if (proposal.get('side')!='BUY' or type(proposal.get('quantity')) is not int or not 0<proposal['quantity']<=2147483647):
        raise PermissionError('Long integral stock entry required')
    raw_limit,raw_stop=number(proposal['limit_price']),number(proposal['stop_price'])
    if not 0<raw_stop<raw_limit:raise ValueError('Explicit lower protective stop required')
    limit=floor_price(proposal['limit_price'],rule['increments'])
    stop=floor_price(proposal['stop_price'],rule['increments'])
    if not 0<stop<limit:raise ValueError('Normalized entry lost lower stop separation')
    with localcontext() as ctx:
        ctx.prec=80
        notional=str(limit*proposal['quantity'])
        distance=str((limit-stop)*proposal['quantity'])
    return dict(symbol=proposal['symbol'],quantity=proposal['quantity'],exchange=exchange,
        con_id=contract['con_id'],market_rule_id=rule['market_rule_id'],
        limit_price=str(limit),stop_price=str(stop),
        notional_usd=notional,
        stop_distance_usd=distance,
        requires_fee_and_risk_revalidation=True,grants_trading_permission=False,
        actual_fill_loss_bounded=False)
