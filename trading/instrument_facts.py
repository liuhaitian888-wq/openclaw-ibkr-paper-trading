"""Typed read-only broker facts. FX-pair positions are not cash balances or permissions."""
import math

# Classification only, not an execution allowlist or a promise of broker support.
FIAT_CODES = frozenset('USD EUR GBP CHF JPY CAD AUD NZD SEK NOK DKK HKD SGD CNH CNY MXN ZAR PLN CZK HUF ILS INR KRW BRL TRY TWD THB RUB AED SAR RON BGN'.split())
CONTRACT_FIELDS = frozenset(('con_id','currency','sec_type'))


def instrument_kind(symbol, contract):
    valid_id=type(contract.get('con_id')) is int and contract['con_id']>0
    if valid_id and contract.get('sec_type')=='STK' and contract.get('currency') in FIAT_CODES:
        return 'SECURITY'
    if (valid_id and contract.get('sec_type')=='CASH' and symbol in FIAT_CODES
            and contract.get('currency') in FIAT_CODES and symbol!=contract['currency']):
        return 'FX_PAIR_POSITION'
    return 'UNSUPPORTED_OR_UNVERIFIED'


def is_fx_pair(symbol, contract):
    return instrument_kind(symbol,contract)=='FX_PAIR_POSITION'


def portfolio_facts(state, *, verified):
    positions=state.get('positions',{}) if verified else {**state.get('last_positions',{}),**state.get('positions',{})}
    result={'securities':[],'fx_pair_positions':[],'unsupported':[],
            'broker_snapshot_verified':bool(verified),'actual_cash_balances_inferred':False,
            'grants_trading_permission':False}
    for symbol,quantity in sorted(positions.items()):
        if quantity==0:continue
        contract=state.get('contracts',{}).get(symbol,{})
        kind=instrument_kind(symbol,contract)
        if type(quantity) not in (int,float) or not math.isfinite(quantity):kind='UNSUPPORTED_OR_UNVERIFIED'
        row={'symbol':symbol,'quantity':quantity,'account':'DUQ503649',**{k:contract.get(k) for k in CONTRACT_FIELDS},
             'classification':kind,'strategy_ownership':'NOT_ASSUMED','current_verified':bool(verified)}
        if kind=='FX_PAIR_POSITION':
            row.update(pair=symbol+'/'+contract['currency'],cash_balance=False,
                       semantics='BROKER_FX_PAIR_POSITION_NOT_ACTUAL_CURRENCY_BALANCE')
        result[{'SECURITY':'securities','FX_PAIR_POSITION':'fx_pair_positions'}.get(kind,'unsupported')].append(row)
    return result


def enrich_execution(old, incoming):
    """Missing contract evidence can be enriched; immutable economics never change."""
    if old is None:return dict(incoming)
    for key in (set(old)|set(incoming))-CONTRACT_FIELDS:
        if old.get(key)!=incoming.get(key):raise ValueError('Conflicting duplicate execId economics')
    merged=dict(old)
    for key in CONTRACT_FIELDS:
        before,after=old.get(key),incoming.get(key)
        if before and after and before!=after:raise ValueError('Conflicting duplicate execId contract')
        if after:merged[key]=after
    return merged
