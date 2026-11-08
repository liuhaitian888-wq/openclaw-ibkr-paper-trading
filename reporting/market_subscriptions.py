"""Owner-declared entitlements and read-only pool/quote projection; no broker calls."""
from contextlib import closing
import hashlib
import json
import re
import sqlite3
import time

from .secretary_read import query


def initialize(archive):
    with closing(archive.connect()) as c, c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS market_subscription_registry(
          package TEXT PRIMARY KEY, payload TEXT NOT NULL, instruction TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS market_watchlist(symbol TEXT PRIMARY KEY, instruction TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS market_subscription_checks(slot INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        ''')


def symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9. -]{0,19}', value):
        raise ValueError('使用大写股票代码，最多20字符')
    return value


def register(archive, instruction, data):
    allowed = {'package', 'environment', 'realtime', 'paper_shared', 'symbols', 'active'}
    if (not isinstance(data, dict) or set(data) != allowed
            or not isinstance(data['package'], str) or not 1 <= len(data['package']) <= 120
            or any(ord(x) < 32 for x in data['package'])
            or data['environment'] not in ('LIVE', 'PAPER')
            or any(type(data[k]) is not bool for k in ('realtime', 'paper_shared', 'active'))
            or not isinstance(data['symbols'], list) or not 1 <= len(data['symbols']) <= 100):
        raise ValueError('用 /marketdata 查看登记JSON模板；需逐项声明适用股票，不能据套餐名称推断覆盖')
    data = {**data, 'symbols': sorted(set(symbol(s) for s in data['symbols'])),
            'source': 'OWNER_DECLARED_NOT_BROKER_VERIFIED'}
    initialize(archive)
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        prior = c.execute("SELECT origin,kind,payload FROM secretary_events WHERE occurrence=?", (instruction,)).fetchone()
        if not prior or prior[:2] != ('USER', 'CONTROL_INSTRUCTION'):
            raise PermissionError('Native owner control instruction required')
        # Bind replay to its original declaration instead of reverting a later edit.
        event = instruction + ':market-registration'
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False)
        old = c.execute('SELECT payload FROM secretary_events WHERE occurrence=?', (event,)).fetchone()
        if old:
            if old[0] != encoded:
                raise ValueError('Registration occurrence conflict')
            return
        c.execute('INSERT INTO secretary_events VALUES(?,?,?,?,?,?,?)',
                  (event, 'der-secretary', 'TOOL', 'MARKET_SUBSCRIPTION_DECLARED', instruction, encoded, archive.clock()))
        c.execute('INSERT INTO market_subscription_registry VALUES(?,?,?,?) ON CONFLICT(package) DO UPDATE SET payload=excluded.payload,instruction=excluded.instruction,updated=excluded.updated',
                  (data['package'], encoded, instruction, archive.clock()))


def watch(archive, instruction, value):
    initialize(archive)
    value = symbol(value)
    with closing(archive.connect()) as c, c:
        prior = c.execute('SELECT origin,kind FROM secretary_events WHERE occurrence=?', (instruction,)).fetchone()
        if prior != ('USER', 'CONTROL_INSTRUCTION'):
            raise PermissionError('Owner control required')
        c.execute('INSERT OR IGNORE INTO market_watchlist VALUES(?,?,?)', (value, instruction, archive.clock()))


def packages(archive):
    initialize(archive)
    with closing(archive.connect()) as c:
        return [dict(json.loads(p), updated=at) for p, at in c.execute('SELECT payload,updated FROM market_subscription_registry ORDER BY package LIMIT 100')]


def quote_status(root, value, now):
    try:
        result = query(root, 'runtime/recovery.sqlite3', '''SELECT
          json_extract(payload,'$.identity') AS identity_ok,
          json_extract(payload,'$.connected') AS connected,
          json_extract(payload,'$.upstream_connected') AS upstream,
          json_extract(payload,'$.last_server_reply') AS reply,
          json_extract(payload,?) AS quote,
          json_extract(payload,?) AS market_type,
          json_extract(payload,?) AS error
          FROM paper_safety_state WHERE id=1''',
          [f'$.quotes."{value}"', f'$.market_types."{value}"', f'$.market_errors."{value}"'], limit=1)
        rows = result.get('rows', [])
        if not rows:
            return 'UNOBSERVED'
        row = rows[0]
        if (not all(row[k] == 1 for k in ('identity_ok', 'connected', 'upstream'))
                or not 0 <= now - float(row['reply']) <= 15):
            return 'STALE_OR_UNVERIFIED'
        error = json.loads(row['error'] or '{}')
        quote = json.loads(row['quote'] or '{}')
        error_current = (isinstance(error.get('observed_at'), (int, float))
                         and 0 <= now-error['observed_at'] <= 21600
                         and error['observed_at'] >= max(quote.get('bid_at') or 0, quote.get('ask_at') or 0))
        if error_current and error.get('code') in (354, 10168, 10186):
            return 'PERMISSION_DENIED'
        if error_current and error.get('code') == 10197:
            return 'SESSION_CONFLICT'
        from trading.symbol_health import classify_symbol
        return classify_symbol({**quote, 'data_type': row['market_type'] or quote.get('data_type')}, now)['status']
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return 'UNOBSERVED'


def declaration(items, value):
    selected = [x for x in items if x['active'] and value in x['symbols']
                and (x['environment'] == 'PAPER' or x['paper_shared'])]
    return ('OWNER_REALTIME' if any(x['realtime'] for x in selected) else
            'OWNER_NON_REALTIME' if selected else 'UNREGISTERED')


def view(root, archive, *, eligible=False, after='', now=None):
    if after:
        symbol(after)
    now = time.time() if now is None else now
    initialize(archive)
    from trading.pool_state import LAYERS
    condition = ' AND current_layer IN ('+','.join('?' for _ in LAYERS[1:])+')' if eligible else ''
    try:
        result = query(root, 'trading_audit.sqlite3',
                       'SELECT symbol,current_layer,updated_at FROM canonical_pool_state WHERE symbol>?'
                       + condition + ' ORDER BY symbol', [after, *LAYERS[1:]] if eligible else [after], limit=21)
        rows = result.get('rows', [])
        evidence = result.get('state')
    except sqlite3.Error:
        rows, evidence = [], 'CANONICAL_TABLE_UNAVAILABLE'
    if not eligible:
        with closing(archive.connect()) as c:
            watched = c.execute('SELECT symbol FROM market_watchlist WHERE symbol>? ORDER BY symbol LIMIT 21', (after,)).fetchall()
        known = {r['symbol'] for r in rows}
        rows += [dict(symbol=s, current_layer='OWNER_WATCH_ONLY', updated_at=None) for (s,) in watched if s not in known]
    items = packages(archive)
    rows = sorted(rows, key=lambda r: r['symbol'])
    more = len(rows) > 20
    rows = rows[:20]
    for row in rows:
        row['canonical_layer_verified'] = row['current_layer'] in LAYERS
        row['subscription'] = declaration(items, row['symbol'])
        row['observed_quote'] = quote_status(root, row['symbol'], now)
    return dict(rows=rows, canonical_evidence=evidence, next_after=rows[-1]['symbol'] if more else None,
                observed_at=now, environment='PAPER', grants_trading_permission=False)


def message(result, *, eligible=False):
    lines = ['合格名单（含已晋级股票）' if eligible else '股票总名单／私人关注']
    labels = {'OWNER_REALTIME': '已登记实时（本人声明）', 'OWNER_NON_REALTIME': '已登记非实时', 'UNREGISTERED': '订阅未登记'}
    lines += [r['symbol']+' · '+r['current_layer']+' · '+labels[r['subscription']]+' · '+r['observed_quote']+' · 资格记录时间='+str(r['updated_at']) for r in result['rows']]
    if not result['rows']:
        lines.append('暂无可展示记录；canonical来源：'+str(result['canonical_evidence']))
    if result['next_after']:
        lines.append('下一页：'+('/eligible ' if eligible else '/universe ')+result['next_after'])
    lines.append('记录来自canonical持久状态，不代表刚刚重新验过资格。环境PAPER；声明与观测分别显示。无实时行情也可 /watch 股票代码 关注，不授予选股资格或交易权限。')
    return '\n'.join(lines)


def registry_message(archive):
    items = packages(archive)
    lines = ['行情订阅登记表｜声明与历史记录，非券商当前认证']
    lines += [p['package']+' · '+p['environment']+' · '+('实时' if p['realtime'] else '非实时')
              +' · Paper共享='+('待核验' if p['paper_shared'] is None else str(p['paper_shared']))+' · active='+str(p['active'])+' · '+','.join(p['symbols'])
              + (' · 历史已验证／当前待复核' if p.get('verification')=='HISTORICAL_RECHECK_REQUIRED' else ' · 本人声明') for p in items]
    if not items:
        lines.append('尚未登记。请从IBKR订阅页面复制真实套餐名；不需要密码、账号或验证码。')
    lines += ['登记／更新（同名套餐覆盖；active=false停用）：',
              '/market_register {"package":"填写真实套餐名","environment":"LIVE","realtime":true,"paper_shared":false,"symbols":["AAPL"],"active":true}',
              'symbols为你明确确认的覆盖股票；不会据套餐名字推断全市场权限。',
              '/market_check 抽查现有证据 · /universe 总名单 · /eligible 合格名单']
    return '\n'.join(lines)[:3400]


def check(archive, root, *, periodic=False, now=None):
    now = time.time() if now is None else now
    initialize(archive)
    slot = int(now // 21600)
    with closing(archive.connect()) as c:
        if periodic and c.execute('SELECT 1 FROM market_subscription_checks WHERE slot=?', (slot,)).fetchone():
            return None
    items = packages(archive)
    # Sample declared coverage in deterministic rotation; no new quote requests.
    symbols = sorted({s for p in items if p['active'] for s in p['symbols']
                      if p['environment'] == 'PAPER' or p['paper_shared']})
    try:
        observed = query(root, 'runtime/recovery.sqlite3',
                         "SELECT j.key AS symbol FROM paper_safety_state s,json_each(json_extract(s.payload,'$.market_types')) j WHERE s.id=1", limit=100).get('rows', [])
        symbols = sorted(set(symbols) | {symbol(r['symbol']) for r in observed})
    except (sqlite3.Error, ValueError, KeyError):
        pass
    start = (slot * 10) % len(symbols) if symbols else 0
    selected = (symbols[start:] + symbols[:start])[:10]
    rows = [dict(symbol=s, subscription=declaration(items, s), observed_quote=quote_status(root, s, now)) for s in selected]
    # Existing monitoring errors can reveal an unregistered entitlement issue.
    try:
        errors = query(root, 'runtime/recovery.sqlite3', '''SELECT j.key AS symbol,
          json_extract(j.value,'$.code') AS code, json_extract(j.value,'$.observed_at') AS at
          FROM paper_safety_state s,json_each(json_extract(s.payload,'$.market_errors')) j
          WHERE s.id=1 AND json_extract(j.value,'$.code') IN (354,10168,10186)''', limit=10).get('rows', [])
    except sqlite3.Error:
        errors = []
    denied = sorted({e['symbol'] for e in errors if isinstance(e['at'], (int, float)) and 0 <= now-e['at'] <= 21600
                     and quote_status(root, e['symbol'], now) == 'PERMISSION_DENIED'})
    result = dict(state='SAMPLED_EXISTING_EVIDENCE' if rows else 'NO_OBSERVED_SYMBOLS', rows=rows, permission_denied=denied, observed_at=now, sample_only=True,
                  method='existing evidence only; no subscriptions or requests', grants_trading_permission=False)
    from .incidents import IncidentStore
    store = IncidentStore(root/'runtime/recovery.sqlite3')
    encoded = json.dumps(result, sort_keys=True)
    if periodic:
        with closing(archive.connect()) as c, c:
            c.execute('INSERT OR IGNORE INTO market_subscription_checks VALUES(?,?)', (slot, encoded))
    if denied:
        fingerprint = hashlib.sha256(json.dumps([int(now // 86400), denied, items], sort_keys=True).encode()).hexdigest()[:20]
        # enqueue and identity dedupe are atomic in the same durable outbox.
        with closing(store.connect()) as c, c:
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'AUTH_MARKET_SUBSCRIPTION',?,'PENDING')",
                      ('market-registration:'+fingerprint, json.dumps(dict(scope='GATEWAY_AUTHENTICATION', severity='YELLOW',
                       reason='行情权限被拒绝：'+','.join(denied)+'。请 /marketdata 核对或登记当前真实套餐及Paper共享；不是自动购买。',
                       action_taken='仅抽查现有行情证据，未新增请求；原有错误与通知保留。', observed_at=now, grants_trading_permission=False))))
    return result
