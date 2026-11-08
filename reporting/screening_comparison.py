"""Read-only field/time/currency comparison; never mistakes daily data for ticks."""
import json
import sqlite3
import time
from .secretary_read import query
from .screening_sources import number


def compare(root, symbol, *, now=None):
    from .market_subscriptions import symbol as validate_symbol
    validate_symbol(symbol)
    now = time.time() if now is None else now
    try:
        rows = query(root, 'agent_secretary.sqlite3', 'SELECT source,payload,observed FROM screen_market_current WHERE symbol=? ORDER BY observed DESC', [symbol], limit=5).get('rows', [])
    except sqlite3.Error:
        rows = []
    external = [dict(json.loads(r['payload']), collected_at=r['observed']) for r in rows]
    try:
        state = query(root, 'runtime/recovery.sqlite3', '''SELECT json_extract(payload,?) AS quote,
          json_extract(payload,?) AS contract,json_extract(payload,?) AS kind,
          json_extract(payload,'$.identity') AS identity_ok,json_extract(payload,'$.connected') AS connected,
          json_extract(payload,'$.upstream_connected') AS upstream,json_extract(payload,'$.last_server_reply') AS reply
          FROM paper_safety_state WHERE id=1''', [f'$.quotes."{symbol}"', f'$.contracts."{symbol}"', f'$.market_types."{symbol}"'], limit=1).get('rows', [])
    except sqlite3.Error:
        state = []
    native = state[0] if state else {}
    quote = json.loads(native.get('quote') or '{}')
    contract = json.loads(native.get('contract') or '{}')
    comparisons = []
    for r in external:
        reasons = []
        if not all(native.get(k) == 1 for k in ('identity_ok', 'connected', 'upstream')) or not 0 <= now-(native.get('reply') or 0) <= 15:
            reasons.append('BROKER_IDENTITY_OR_HEARTBEAT_UNVERIFIED')
        if not contract.get('con_id') or contract.get('sec_type') != 'STK':
            reasons.append('IBKR_CONTRACT_UNVERIFIED')
        if contract.get('external_identity_verified') is not True or contract.get('external_symbol')!=symbol:
            reasons.append('CROSS_SOURCE_CONTRACT_MAPPING_UNVERIFIED')
        if r.get('currency') != 'USD' or contract.get('currency') != 'USD':
            reasons.append('CURRENCY_UNVERIFIED')
        if native.get('kind') != 1:
            reasons.append('BROKER_REALTIME_TYPE_UNVERIFIED')
        price = number(quote.get('last'))
        event_at = number(quote.get('event_time'))
        if price is None or price <= 0 or not 0 <= now-(quote.get('last_at') or 0) <= 10:
            reasons.append('BROKER_LAST_TRADE_MISSING_OR_STALE')
        if not r.get('price_at') or not event_at or abs(r['price_at']-event_at) > 60:
            reasons.append('TRADE_TIMES_NOT_ALIGNED_OR_DATE_ONLY')
        if not r.get('price_at') or not 0 <= now-r['price_at'] <= 120:
            reasons.append('EXTERNAL_QUOTE_NOT_CURRENT')
        if r.get('price') is None or r['price'] <= 0:
            reasons.append('EXTERNAL_PRICE_MISSING')
        gap = (r['price']-price)/price*100 if not reasons else None
        comparisons.append(dict(source=r['source'], external_price=r.get('price'), external_date=r.get('price_date'),
                                external_at=r.get('price_at'), broker_price=price, broker_event_at=event_at,
                                status='TIME_ALIGNED_OBSERVATION' if not reasons else 'NOT_DIRECTLY_COMPARABLE',
                                difference_pct=gap, reasons=reasons))
    try:
        facts = query(root, 'agent_secretary.sqlite3', '''SELECT f.metric,f.period,f.payload FROM screen_fundamentals f
          JOIN screen_cik_mapping m ON m.cik=f.cik WHERE m.symbol=? ORDER BY f.period DESC LIMIT 8''', [symbol], limit=8).get('rows', [])
    except sqlite3.Error:
        facts = []
    return dict(symbol=symbol, environment='PAPER', external=external, broker_quote=quote,
                broker_contract=contract, comparisons=comparisons, fundamentals=facts,
                realtime_permission='PENDING', live_account_queried=False, grants_trading_permission=False)


def message(r):
    lines = [r['symbol']+'｜外部研究数据 ↔ 已有IBKR Paper回读']
    if not r['comparisons']:
        lines.append('暂无外部价格；请 /screen_refresh。')
    for c in r['comparisons']:
        lines.append(c['source']+'：'+str(c['external_price'])+'（'+str(c['external_date'])+'）／券商最近成交 '+str(c['broker_price']))
        lines.append(c['status']+' · '+(','.join(c['reasons']) if c['reasons'] else '差异 '+str(round(c['difference_pct'], 4))+'%'))
    names = {'assets': '资产', 'equity': '股东权益', 'revenue': '季度营收', 'net_income': '季度净利润'}
    for f in r['fundamentals'][:4]:
        p = json.loads(f['payload'])
        lines.append('SEC '+names.get(f['metric'], f['metric'])+' '+str(p['value'])+' '+p['unit']+' · 截至 '+p['end']+' · '+p['period'])
    if not r['fundamentals']:
        lines.append('SEC基本面缺失／映射未确认，不填零。')
    lines.append('季度财报不是实时估值；未计算未经核对的PE。权限仍待核验，未查询Live，也不据非同期差异判错。')
    return '\n'.join(lines)[:3200]
