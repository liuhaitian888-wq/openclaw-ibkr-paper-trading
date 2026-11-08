"""Versioned coarse research and six-layer projections. No execution authority."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
import time
import uuid

from . import screening_sources as sources
from .secretary_read import query


def initialize(archive):
    with closing(archive.connect()) as c, c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS screen_market_current(source TEXT,symbol TEXT,payload TEXT,observed REAL,run TEXT,PRIMARY KEY(source,symbol));
        CREATE TABLE IF NOT EXISTS screen_fundamentals(cik INTEGER,metric TEXT,period TEXT,payload TEXT,observed REAL,run TEXT,PRIMARY KEY(cik,metric,period));
        CREATE TABLE IF NOT EXISTS screen_cik_mapping(symbol TEXT PRIMARY KEY,cik INTEGER,observed REAL);
        CREATE TABLE IF NOT EXISTS screen_source_status(source TEXT PRIMARY KEY,state TEXT,observed REAL,payload TEXT);
        CREATE TABLE IF NOT EXISTS screen_source_retry(url TEXT PRIMARY KEY,payload TEXT);
        CREATE TABLE IF NOT EXISTS screen_versions(id TEXT PRIMARY KEY,source TEXT,url TEXT,sha256 TEXT,path TEXT,collected REAL);
        CREATE TABLE IF NOT EXISTS screen_refresh_jobs(id TEXT PRIMARY KEY,origin TEXT,state TEXT,queued REAL,started REAL,finished REAL,result TEXT);
        CREATE TABLE IF NOT EXISTS screen_pool_projection(security_id TEXT PRIMARY KEY,symbol TEXT,network TEXT,
          layer TEXT,price REAL,volume REAL,market_cap REAL,source TEXT,data_date TEXT,expires REAL,payload TEXT,run TEXT);
        CREATE INDEX IF NOT EXISTS screen_projection_filter ON screen_pool_projection(layer,network,volume,security_id);
        CREATE TABLE IF NOT EXISTS broker_screen_requests(id TEXT PRIMARY KEY,code TEXT,state TEXT,queued REAL,expires REAL,
          started REAL,finished REAL,connection TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS broker_screen_results(request TEXT,rank INTEGER,symbol TEXT,con_id INTEGER,
          exchange TEXT,currency TEXT,sec_type TEXT,observed REAL,PRIMARY KEY(request,rank));
        ''')


def enqueue(archive, *, origin, identity=None, now=None):
    now = time.time() if now is None else now
    initialize(archive)
    identity = identity or 'manual:'+str(uuid.uuid4())
    with closing(archive.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        prior = c.execute("SELECT id,state FROM screen_refresh_jobs WHERE state IN ('QUEUED','STARTED') ORDER BY queued LIMIT 1").fetchone()
        if prior:
            return dict(id=prior[0], state=prior[1], reused=True)
        recent = c.execute("SELECT id,state FROM screen_refresh_jobs WHERE state='SUCCEEDED' AND finished>? ORDER BY finished DESC LIMIT 1", (now-300,)).fetchone()
        if recent:
            return dict(id=recent[0], state=recent[1], reused=True)
        c.execute("INSERT OR IGNORE INTO screen_refresh_jobs VALUES(?,?,'QUEUED',?,NULL,NULL,NULL)", (identity, origin, now))
        row = c.execute('SELECT state FROM screen_refresh_jobs WHERE id=?', (identity,)).fetchone()
    return dict(id=identity, state=row[0], reused=False)


def schedule(archive, now=None):
    from zoneinfo import ZoneInfo
    now = time.time() if now is None else now
    berlin = datetime.fromtimestamp(now, ZoneInfo('Europe/Berlin'))
    new_york = datetime.fromtimestamp(now, ZoneInfo('America/New_York'))
    due = []
    if berlin.hour == 8 and 25 <= berlin.minute < 40:
        due.append('morning:'+str(berlin.date()))
    if new_york.weekday() < 5 and new_york.hour == 18 and 20 <= new_york.minute < 35:
        due.append('after-close:'+str(new_york.date()))
    for slot in due:
        enqueue(archive, origin='SCHEDULE', identity='schedule:'+slot, now=now)


def source_status(archive, name, state, payload, now):
    with closing(archive.connect()) as c, c:
        c.execute('INSERT OR REPLACE INTO screen_source_status VALUES(?,?,?,?)', (name, state, now, json.dumps(payload)))


def ingest_market(archive, name, rows, info, run, now):
    if not rows or len({r['symbol'] for r in rows}) != len(rows):
        raise ValueError('Unique nonempty research market rows required')
    with closing(archive.connect()) as c, c:
        c.execute('DELETE FROM screen_market_current WHERE source=?', (name,))
        c.executemany('INSERT INTO screen_market_current VALUES(?,?,?,?,?)',
                      [(name, r['symbol'], json.dumps(r, allow_nan=False), now, run) for r in rows])
    source_status(archive, name, 'AVAILABLE_RESEARCH', info, now)


def rebuild(archive, root, *, now=None, run='projection'):
    """Materialize research L1-L3 only; never write canonical_pool_state."""
    from trading.pool_state import LAYERS
    now = time.time() if now is None else now
    initialize(archive)
    with closing(archive.connect()) as c:
        directory = c.execute("SELECT security_id,symbol,network,asset_type FROM market_security_master WHERE active=1 AND network IN ('A','B','C') ORDER BY security_id LIMIT 30001").fetchall()
        if len(directory) > 30000:
            raise ValueError('Directory exceeds research capacity')
        market = {}
        for sym, raw in c.execute('SELECT symbol,payload FROM screen_market_current LIMIT 40001'):
            r = json.loads(raw)
            prior = market.get(sym)
            key = (r.get('price_date') or '', r.get('price_at') or 0, r.get('price') is not None)
            if prior is None or key > prior[0]:
                market[sym] = (key, r)
        source_states=dict(c.execute('SELECT source,state FROM screen_source_status'))
        mapping = dict(c.execute('SELECT symbol,cik FROM screen_cik_mapping'))
        fundamentals = {}
        for cik, metric, raw in c.execute('SELECT cik,metric,payload FROM screen_fundamentals LIMIT 100001'):
            fact = json.loads(raw)
            if fact['end'] > fundamentals.get(cik, {}).get(metric, {}).get('end', ''):
                fundamentals.setdefault(cik, {})[metric] = fact
        scanner = {sym: dict(request=req, observed=at) for sym, req, at in c.execute('''SELECT r.symbol,r.request,r.observed
          FROM broker_screen_results r JOIN broker_screen_requests j ON j.id=r.request
          WHERE j.state='SUCCEEDED' AND r.observed>? ORDER BY r.observed''', (now-3600,))}
    rows = []
    for identity, sym, network, kind in directory:
        m = market.get(sym, (None, {}))[1]
        facts = fundamentals.get(mapping.get(sym), {})
        flags = []
        price, volume = m.get('price'), m.get('volume')
        date = m.get('price_date')
        age = None
        if date:
            age = (datetime.fromtimestamp(now, timezone.utc).date()-datetime.strptime(date, '%Y-%m-%d').date()).days
        if m and source_states.get(m.get('source'))!='AVAILABLE_RESEARCH':
            flags.append('SOURCE_REFRESH_FAILED_USING_CACHE')
        if price is None:
            flags.append('PRICE_MISSING')
        elif price<=0:
            flags.append('PRICE_INVALID')
        if volume is None:
            flags.append('SESSION_VOLUME_MISSING')
        if age is None:
            flags.append('PRICE_TIME_UNKNOWN')
        elif not 0 <= age <= 7:
            flags.append('PRICE_DATE_STALE_OR_FUTURE')
        if m.get('currency') != 'USD':
            flags.append('CURRENCY_UNVERIFIED')
        if m.get('average_volume') is None:
            flags.append('AVERAGE_VOLUME_MISSING')
        if len(facts) < 4:
            flags.append('FUNDAMENTALS_PARTIAL_OR_MISSING')
        if kind != 'STOCK':
            flags.append('NOT_COMMON_STOCK_RESEARCH_SCOPE')
        coarse = bool(kind == 'STOCK' and price is not None and price >= 5 and volume is not None and volume >= 1_000_000
                      and age is not None and 0 <= age <= 7 and m.get('currency') == 'USD')
        layer = LAYERS[2] if coarse and sym in scanner else LAYERS[1] if coarse else LAYERS[0]
        expiry = now+86400
        if date:
            expiry = min(expiry, datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()+8*86400)
        if layer == LAYERS[2]:
            expiry = min(expiry, scanner[sym]['observed']+3600)
        payload = dict(strategy='coarse_liquidity_v1', research_only=True, canonical_execution_active=False,
                       fields=m, fundamentals=facts, cik=mapping.get(sym), scanner=scanner.get(sym),
                       flags=flags, runtime_blocks=['REALTIME_PERMISSION_PENDING', 'IBKR_CONTRACT_UNVERIFIED',
                       'STRATEGY_SIGNAL_NOT_VERIFIED', 'RISK_AND_EXECUTION_GATES_INDEPENDENT'],
                       layer_scope='RESEARCH_PROJECTION_NOT_CANONICAL_AUTHORITY', published_at=now,
                       fundamentals_point_in_time_verified=False, grants_trading_permission=False)
        rows.append((identity, sym, network, layer, price, volume, m.get('market_cap'), m.get('source'), date,
                     expiry, json.dumps(payload, allow_nan=False), run))
    with closing(archive.connect()) as c, c:
        c.execute('DELETE FROM screen_pool_projection')
        c.executemany('INSERT INTO screen_pool_projection VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    return dict(rows=len(rows), coarse_candidates=sum(r[3] != LAYERS[0] for r in rows),
                scanner_cross_candidates=sum(r[3] == LAYERS[2] for r in rows), grants_trading_permission=False)


def refresh(archive, root, run, *, sec_email=None, loader=sources.fetch, now=None):
    now = time.time() if now is None else now
    initialize(archive)
    folder = Path(root)/'screening'/'snapshots'/run.replace(':', '_')
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    with closing(archive.connect()) as c:
        retry = {u: json.loads(p) for u, p in c.execute('SELECT url,payload FROM screen_source_retry')}
    counter = 0
    def get(url):
        nonlocal counter
        raw = loader(url, sec_email=sec_email, retry=retry, now=now)
        counter += 1
        path = folder/(str(counter)+'.json')
        path.write_bytes(raw)
        with closing(archive.connect()) as c, c:
            c.execute('INSERT INTO screen_versions VALUES(?,?,?,?,?,?)',
                      (run+':'+str(counter), urlsplit_source(url), url, hashlib.sha256(raw).hexdigest(), str(path), now))
        return raw
    outcomes = {}
    def attempt(name, function):
        try:
            result = function()
            outcomes[name] = result if isinstance(result,str) and result.startswith('AVAILABLE_') else 'AVAILABLE_RESEARCH'
            return result
        except Exception as exc:
            outcomes[name] = type(exc).__name__
            source_status(archive, name, 'UNAVAILABLE_OR_BACKOFF',
                          dict(error_type=type(exc).__name__, http_status=getattr(exc, 'code', None), prior_data_preserved=True), now)
            return None
    try:
        def nasdaq():
            rows, info = sources.nasdaq(get(sources.NASDAQ), get(sources.NASDAQ_DATE))
            if len(rows) < 500:
                raise ValueError('Broad source unexpectedly small')
            ingest_market(archive, 'NASDAQ_SCREENER', rows, info, run, now)
        attempt('NASDAQ_SCREENER', nasdaq)
        def yahoo():
            all_rows = {}; total = None
            for offset in (0, 250):
                rows, info = sources.yahoo(get(sources.YAHOO+str(offset)))
                all_rows.update({r['symbol']: r for r in rows}); total = info['provider_total']
                if not isinstance(total, (int, float)) or len(all_rows) >= total or len(rows) < 250:
                    break
            ingest_market(archive, 'YAHOO_MOST_ACTIVE', list(all_rows.values()),
                          dict(rows=len(all_rows), provider_total=total, partial=True, scope='PREDEFINED_LIST_NOT_FULL_UNIVERSE'), run, now)
        attempt('YAHOO_MOST_ACTIVE', yahoo)
        with closing(archive.connect()) as c:
            recent = c.execute("SELECT observed FROM screen_source_status WHERE source='SEC_FRAMES' AND state IN ('AVAILABLE_RESEARCH','AVAILABLE_PARTIAL_RESEARCH')").fetchone()
        if not recent or not 0 <= now-recent[0] < 72000:
            def sec():
                mapping = sources.sec_mapping(get(sources.SEC_MAPPING))
                time.sleep(.5)
                year, quarter = sources.completed_quarter(now)
                results = [];metric_errors={}
                for metric, tag, instant in [('assets', 'Assets', True), ('equity', 'StockholdersEquity', True),
                                             ('net_income', 'NetIncomeLoss', False),
                                             ('revenue', 'RevenueFromContractWithCustomerExcludingAssessedTax', False)]:
                    period = f'CY{year}Q{quarter}'+('I' if instant else '')
                    url = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json'
                    # Every field keeps its own end/start/units; no TTM or PE inference.
                    try:
                        values = sources.sec_frame(get(url), tag=tag, unit='USD', period=period)
                        results.extend((cik, metric, period, json.dumps(value), now, run) for cik, value in values.items())
                    except Exception as exc:
                        metric_errors[metric]={'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}
                        if getattr(exc,'code',None) in (403,429):break
                    time.sleep(.5)
                with closing(archive.connect()) as c, c:
                    c.execute('DELETE FROM screen_cik_mapping')
                    c.executemany('INSERT INTO screen_cik_mapping VALUES(?,?,?)', [(sym, cik, now) for sym, cik in mapping.items()])
                    c.executemany('INSERT OR REPLACE INTO screen_fundamentals VALUES(?,?,?,?,?,?)', results)
                source_status(archive, 'SEC_FRAMES', 'AVAILABLE_PARTIAL_RESEARCH' if metric_errors else 'AVAILABLE_RESEARCH',
                              dict(metric_errors=metric_errors,rows=len(results), tickers=len(mapping), period=f'CY{year}Q{quarter}',
                                   missing_tags_not_zero=True, point_in_time_verified=False), now)
                return 'AVAILABLE_PARTIAL_RESEARCH' if metric_errors else 'AVAILABLE_RESEARCH'
            attempt('SEC_FRAMES', sec)
        else:
            outcomes['SEC_FRAMES'] = 'CACHED_LT_20H'
        projection = rebuild(archive, root, now=now, run=run)
        result = dict(sources=outcomes, projection=projection, snapshot=str(folder), observed_at=now,
                      scope='RESEARCH_ONLY', grants_trading_permission=False)
        (folder/'manifest.json').write_text(json.dumps(result, sort_keys=True))
        return result
    finally:
        with closing(archive.connect()) as c, c:
            c.execute('DELETE FROM screen_source_retry')
            c.executemany('INSERT INTO screen_source_retry VALUES(?,?)', [(u, json.dumps(v)) for u, v in retry.items()])


def urlsplit_source(url):
    from urllib.parse import urlsplit
    return urlsplit(url).hostname


def view(root, text='', now=None):
    now = time.time() if now is None else now
    options = {}
    for token in shlex.split(text or "min_price=5 min_volume=1000000"):
        if '=' not in token:
            raise ValueError('筛选示例：network=C min_price=5 min_volume=1000000 q=Apple')
        k, v = token.split('=', 1)
        if k in options or k not in ('network', 'q', 'min_price', 'min_volume', 'min_cap', 'layer', 'after') or not 0 < len(v) <= 100:
            raise ValueError('Unsupported screening filter')
        options[k] = v
    where = ['1=1']; params = []
    for k, col in [('min_price', 'price'), ('min_volume', 'volume'), ('min_cap', 'market_cap')]:
        if k in options:
            value = sources.number(options[k])
            if value is None or not 0 <= value <= 1e16:
                raise ValueError('Finite nonnegative screening threshold required')
            where.append(col+'>=?'); params.append(value)
    if 'network' in options:
        if options['network'].upper() not in ('A', 'B', 'C'):
            raise ValueError('ABC network required')
        where.append('network=?'); params.append(options['network'].upper())
    if 'q' in options:
        where.append('instr(upper(symbol),upper(?))>0'); params.append(options['q'])
    if 'layer' in options:
        if options['layer'] not in ('1', '2', '3'):
            raise ValueError('Research layers only 1/2/3; layers 4–6 require independent evidence')
        from trading.pool_state import LAYERS
        where.append('layer=? AND expires>?'); params += [LAYERS[int(options['layer'])-1], now]
    condition = ' AND '.join(where)
    try:
        total = query(root, 'agent_secretary.sqlite3', 'SELECT count(*) AS n FROM screen_pool_projection WHERE '+condition, params, limit=1)['rows'][0]['n']
        if 'after' in options:
            where.append('security_id>?'); params.append(options['after'])
        rows = query(root, 'agent_secretary.sqlite3', '''SELECT security_id,symbol,network,layer,price,volume,source,data_date,expires,
           json_extract(payload,'$.flags') AS flags FROM screen_pool_projection WHERE '''+' AND '.join(where)+' ORDER BY security_id', params, limit=13).get('rows', [])
        next_options = {**options, 'after': rows[11]['security_id']} if len(rows) > 12 else None
        for row in rows[:12]:
            row['stale'] = row['expires'] < now
        return dict(state='RESEARCH_PROJECTION', total=total, rows=rows[:12], next=next_options)
    except (sqlite3.Error, IndexError, KeyError):
        return dict(state='NOT_CREATED', total=0, rows=[], next=None)


def message(result):
    lines = ['宽范围研究筛选｜'+str(result['total'])+' 项 · '+result['state']]
    for r in result['rows']:
        layer = '已过期' if r['stale'] else {'MASTER_UNIVERSE':'L1资料／条件待补','ELIGIBLE_UNIVERSE':'L2研究初筛','SCAN_POOL':'L3券商交叉候选'}.get(r['layer'],r['layer'])
        lines.append(r['symbol']+' · '+r['network']+'网 · '+layer+' · 价 '+str(r['price'])+' · 当日量 '+str(r['volume'])
                     +' · '+str(r['data_date'])+' · '+str(r['source']))
        flag_names={'PRICE_MISSING':'缺价格','PRICE_INVALID':'价格无效','SESSION_VOLUME_MISSING':'缺当日量',
                    'PRICE_TIME_UNKNOWN':'价格日期不明','PRICE_DATE_STALE_OR_FUTURE':'价格日期失效',
                    'CURRENCY_UNVERIFIED':'币种待核验','AVERAGE_VOLUME_MISSING':'缺平均量',
                    'FUNDAMENTALS_PARTIAL_OR_MISSING':'基本面不全','NOT_COMMON_STOCK_RESEARCH_SCOPE':'非普通股初筛范围',
                    'SOURCE_REFRESH_FAILED_USING_CACHE':'来源失败／使用旧缓存'}
        flags=json.loads(r.get('flags') or '[]') if isinstance(r.get('flags'),str) else r.get('flags',[])
        if flags:lines.append('  标记：'+'、'.join(flag_names.get(f,f) for f in flags))
    if result['next']:
        lines.append('下一页：/screen '+' '.join(k+'='+shlex.quote(v) for k, v in result['next'].items()))
    lines += ['L1/L2/L3为研究投影，不是canonical交易资格。所有实时权限待核验；缺值显示None，不填零。',
              '/screen min_price=5 min_volume=1000000 layer=2 · /compare 股票 · /data_status 查看覆盖和维护']
    return '\n'.join(lines)


def status(root):
    try:
        result = query(root, 'agent_secretary.sqlite3', 'SELECT source,state,observed,payload FROM screen_source_status ORDER BY source', limit=10)
        jobs = query(root, 'agent_secretary.sqlite3', 'SELECT id,state,queued,finished FROM screen_refresh_jobs ORDER BY queued DESC LIMIT 1', limit=1)
        layers = query(root, 'agent_secretary.sqlite3', 'SELECT layer,count(*) AS n FROM screen_pool_projection GROUP BY layer', limit=10)
        scanners=query(root,'agent_secretary.sqlite3','SELECT code,state,finished,payload FROM broker_screen_requests ORDER BY queued DESC LIMIT 3',limit=3)
    except sqlite3.Error:
        return '筛选数据尚未建立；/screen_refresh 可排队首次维护。'
    lines = ['数据来源与维护｜所有结果仅研究']
    lines += [r['source']+' · '+r['state']+' · 检查 '+str(r['observed'])+' · '+r['payload'][:400] for r in result.get('rows', [])]
    lines += ['最近任务：'+json.dumps(jobs.get('rows', []), ensure_ascii=False), '研究层：'+json.dumps(layers.get('rows', []), ensure_ascii=False),
              '真实券商扫描：'+json.dumps(scanners.get('rows',[]),ensure_ascii=False),
              '目录：每日08:10 Berlin；价量：08:25 Berlin／工作日18:20 New York；SEC：至少间隔20小时。',
              '按需任务约1分钟领取；/scan 使用既有Paper连接。免费接口无全覆盖／实时保证，UNKNOWN不重放。']
    return '\n'.join(lines)
