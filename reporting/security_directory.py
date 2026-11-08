"""Versioned public listing directory, independent of execution/quote permissions."""
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import time
import urllib.request
import uuid

from .secretary_read import query

SOURCES = {name: 'https://www.nasdaqtrader.com/dynamic/SymDir/'+name+'.txt'
           for name in ('nasdaqlisted', 'otherlisted')}
EXCHANGES = {'NASDAQ': ('NASDAQ', 'C'), 'N': ('NYSE', 'A'),
             'A': ('NYSE_AMERICAN', 'B'), 'P': ('NYSE_ARCA', 'B'),
             'Z': ('CBOE_BZX', 'B'), 'V': ('IEX', 'B')}
PAGE_SIZE = 12


def initialize(archive):
    with closing(archive.connect()) as c, c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS market_security_master(
          security_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,name TEXT NOT NULL,
          exchange TEXT NOT NULL,network TEXT NOT NULL,asset_type TEXT NOT NULL,
          source_symbol TEXT NOT NULL,cqs_symbol TEXT,nasdaq_symbol TEXT,
          financial_status TEXT,source TEXT NOT NULL,source_created TEXT NOT NULL,
          revision TEXT NOT NULL,last_seen REAL NOT NULL,active INTEGER NOT NULL,
          permission_status TEXT NOT NULL DEFAULT 'PENDING');
        CREATE INDEX IF NOT EXISTS market_master_filter ON market_security_master(active,network,asset_type,security_id);
        CREATE INDEX IF NOT EXISTS market_master_symbol ON market_security_master(symbol);
        CREATE TABLE IF NOT EXISTS security_master_refreshes(
          occurrence TEXT PRIMARY KEY,started REAL NOT NULL,finished REAL,state TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS security_master_current(id INTEGER PRIMARY KEY CHECK(id=1),revision TEXT NOT NULL,payload TEXT NOT NULL);
        ''')


def fetch(name):
    request = urllib.request.Request(SOURCES[name], headers={'User-Agent': 'buy-der-security-directory/1.0'})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Directory response exceeds bound')
    return data


def asset_type(name, etf):
    if etf == 'Y':
        return 'ETF'
    if re.search(r'warrant|rights|preferred|depositary.*(?:%|rate)|notes due|debentures', name, re.I):
        return 'OTHER'
    if re.search(r'common stock|ordinary shares|common shares', name, re.I):
        return 'STOCK'
    return 'OTHER'  # preferreds, warrants, units, debt and unresolved types


def parse(data, name, *, now, minimum=1000):
    text = data.decode('utf-8-sig', errors='strict')
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[-1].startswith('File Creation Time: '):
        raise ValueError('Complete official directory with footer required')
    created = lines[-1].split('|')[0].removeprefix('File Creation Time: ').strip()
    stamp = datetime.strptime(created, '%m%d%Y%H:%M')
    age = (datetime.fromtimestamp(now, timezone.utc).date()-stamp.date()).days
    if not 0 <= age <= 14:
        raise ValueError('Directory date future or older than 14 days')
    reader = csv.DictReader(io.StringIO('\n'.join(lines[:-1])), delimiter='|')
    required = {'Security Name', 'Test Issue', 'ETF'} | ({'Symbol', 'Financial Status'} if name == 'nasdaqlisted'
                                                      else {'ACT Symbol', 'Exchange', 'CQS Symbol', 'NASDAQ Symbol'})
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('Directory header mismatch')
    records = []; seen = set(); tests = 0
    for row in reader:
        raw = row.get('Symbol') if name == 'nasdaqlisted' else row.get('ACT Symbol')
        title = row.get('Security Name')
        if (not isinstance(raw, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.$^=/+\-]{0,31}', raw)
                or not isinstance(title, str) or not 0 < len(title) <= 255
                or row['Test Issue'] not in ('N', 'Y') or row['ETF'] not in ('N', 'Y')
                or None in row):
            raise ValueError('Invalid directory record')
        if raw in seen:
            raise ValueError('Duplicate source security identity')
        seen.add(raw)
        if row['Test Issue'] == 'Y':
            tests += 1
            continue
        code = 'NASDAQ' if name == 'nasdaqlisted' else row['Exchange']
        exchange, network = EXCHANGES.get(code, ('UNMAPPED:'+code, 'UNKNOWN'))
        records.append(dict(security_id=name+':'+raw, symbol=raw, name=title,
                            exchange=exchange, network=network, asset_type=asset_type(title, row['ETF']),
                            source_symbol=raw, cqs_symbol=row.get('CQS Symbol', ''),
                            nasdaq_symbol=row.get('NASDAQ Symbol', raw), financial_status=row.get('Financial Status', ''),
                            source=SOURCES[name], source_created=created))
    if len(records) < minimum or len(records) > 30000:
        raise ValueError('Directory count outside accepted range')
    return records, dict(source=SOURCES[name], sha256=hashlib.sha256(data).hexdigest(),
                         source_created=created, source_age_days=age, accepted=len(records), excluded_test_issues=tests)


def refresh(archive, root, *, loader=fetch, now=None, minimum=1000):
    now = time.time() if now is None else now
    initialize(archive)
    occurrence = str(uuid.uuid4())
    folder = Path(root)/'security-directory'/'snapshots'/occurrence
    folder.mkdir(parents=True, mode=0o700)
    with closing(archive.connect()) as c, c:
        c.execute('INSERT INTO security_master_refreshes VALUES(?,?,NULL,?,?)',
                  (occurrence, now, 'STARTED', json.dumps({'snapshot': str(folder)})))
    try:
        records = []; sources = []
        for name in SOURCES:
            raw = loader(name)
            (folder/(name+'.txt')).write_bytes(raw)
            rows, info = parse(raw, name, now=now, minimum=minimum)
            records.extend(rows); sources.append(info)
        revision = hashlib.sha256(json.dumps([(x['source'], x['sha256']) for x in sources]).encode()).hexdigest()
        payload = dict(revision=revision, sources=sources, count=len(records), collected_at=now,
                       snapshot=str(folder), permission_status='PENDING', grants_trading_permission=False)
        (folder/'manifest.json').write_text(json.dumps(payload, sort_keys=True))
        with closing(archive.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            prior = c.execute('SELECT payload FROM security_master_current WHERE id=1').fetchone()
            if prior:
                previous = json.loads(prior[0])
                if len(records) < previous['count']*.8:
                    raise ValueError('Directory shrank more than 20%; preserve prior and reconcile')
                # Also prevent replaying an older directory over a newer snapshot.
                for old, new in zip(previous['sources'], sources):
                    if datetime.strptime(new['source_created'], '%m%d%Y%H:%M') < datetime.strptime(old['source_created'], '%m%d%Y%H:%M'):
                        raise ValueError('Directory timestamp regressed')
            c.execute('UPDATE market_security_master SET active=0')
            for record in records:
                values = [record[k] for k in ('security_id', 'symbol', 'name', 'exchange', 'network', 'asset_type',
                                              'source_symbol', 'cqs_symbol', 'nasdaq_symbol', 'financial_status', 'source', 'source_created')]
                c.execute('''INSERT INTO market_security_master VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'PENDING')
                  ON CONFLICT(security_id) DO UPDATE SET symbol=excluded.symbol,name=excluded.name,
                  exchange=excluded.exchange,network=excluded.network,asset_type=excluded.asset_type,
                  cqs_symbol=excluded.cqs_symbol,nasdaq_symbol=excluded.nasdaq_symbol,financial_status=excluded.financial_status,
                  source=excluded.source,source_created=excluded.source_created,revision=excluded.revision,
                  last_seen=excluded.last_seen,active=1,permission_status='PENDING' ''', (*values, revision, now))
            c.execute('INSERT OR REPLACE INTO security_master_current VALUES(1,?,?)', (revision, json.dumps(payload)))
            c.execute('UPDATE security_master_refreshes SET finished=?,state=?,payload=? WHERE occurrence=?',
                      (time.time(), 'SUCCEEDED', json.dumps(payload), occurrence))
        return payload
    except Exception as exc:
        with closing(archive.connect()) as c, c:
            c.execute('UPDATE security_master_refreshes SET finished=?,state=?,payload=? WHERE occurrence=?',
                      (time.time(), 'FAILED', json.dumps({'error_type': type(exc).__name__, 'snapshot': str(folder)}), occurrence))
        raise


def filters(text):
    result = {}
    for part in shlex.split(text):
        if '=' not in part:
            # Compatibility with the old symbol-only next-page command.
            part = 'after='+part
        key, value = part.split('=', 1)
        if key in result or key not in ('network', 'type', 'permission', 'q', 'after') or not 0 < len(value) <= 100:
            raise ValueError('筛选：network=A/B/C/UNKNOWN type=STOCK/ETF/OTHER permission=PENDING q=代码或名称')
        if key in ('network', 'type', 'permission'):
            value = value.upper()
        result[key] = value
    for key, allowed in [('network', ('A', 'B', 'C', 'UNKNOWN')), ('type', ('STOCK', 'ETF', 'OTHER')), ('permission', ('PENDING',))]:
        if key in result and result[key] not in allowed:
            raise ValueError('Unsupported directory filter '+key)
    if 'after' in result and not re.fullmatch(r'[A-Za-z0-9:.$^=/+\-]{1,80}', result['after']):
        raise ValueError('Invalid page cursor')
    return result


def view(root, text='', *, now=None):
    selection = filters(text)
    where = ['active=1']; params = []
    for key, column in [('network', 'network'), ('type', 'asset_type'), ('permission', 'permission_status')]:
        if key in selection:
            where.append(column+'=?'); params.append(selection[key])
    if 'q' in selection:
        # Literal substring, not a user-defined LIKE pattern.
        where.append('(instr(upper(symbol),upper(?))>0 OR instr(upper(name),upper(?))>0)')
        params += [selection['q'], selection['q']]
    if 'network' not in selection:
        where.append("network IN ('A','B','C')")
    base = ' AND '.join(where)
    try:
        total = query(root, 'agent_secretary.sqlite3', 'SELECT count(*) AS n FROM market_security_master WHERE '+base, params, limit=1)['rows'][0]['n']
        if 'after' in selection:
            where.append('security_id>?'); params.append(selection['after'])
        rows = query(root, 'agent_secretary.sqlite3', '''SELECT security_id,symbol,name,exchange,network,asset_type,
                       permission_status,source_created,last_seen FROM market_security_master WHERE '''+' AND '.join(where)
                       +' ORDER BY security_id', params, limit=PAGE_SIZE+1).get('rows', [])
        status = query(root, 'agent_secretary.sqlite3', 'SELECT state,started FROM security_master_refreshes ORDER BY started DESC,rowid DESC LIMIT 1', limit=1).get('rows', [])
    except (__import__('sqlite3').Error, KeyError, IndexError):
        return dict(state='DIRECTORY_NOT_READY', rows=[], total=0, filters=selection)
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    next_filters = {**selection, 'after': rows[-1]['security_id']} if more else None
    return dict(state='REFERENCE_DIRECTORY', rows=rows, total=total, filters=selection, next_filters=next_filters,
                refresh=status[0] if status else None, grants_trading_permission=False)


def message(result):
    if result['state'] == 'DIRECTORY_NOT_READY':
        return '证券总目录尚未发布；不能把运行候选表当完整总名单。'
    lines = ['证券总名单｜筛选命中 '+str(result['total'])+' 项']
    kinds = {'STOCK': '普通股／普通股份', 'ETF': 'ETF', 'OTHER': '其他上市证券'}
    for row in result['rows']:
        lines.append(row['symbol']+' · '+row['name'][:38]+' · '+row['network']+'网 · '+kinds[row['asset_type']]
                     +' · 实时权限待核验'+(' · '+row.get('observed_quote', '') if row.get('observed_quote') else ''))
    if result['rows']:
        lines.append('目录源时间：'+', '.join(sorted({r['source_created'] for r in result['rows']}))+'（源文件原格式，无时区推断）')
    if (result.get('refresh') or {}).get('state') != 'SUCCEEDED':
        lines.append('最近刷新未成功／未完成；当前展示上次成功目录。')
    if result['next_filters']:
        lines.append('下一页：/universe '+' '.join(k+'='+shlex.quote(v) for k, v in result['next_filters'].items()))
    lines += ['筛选：/universe network=C type=STOCK permission=PENDING q=Apple',
              '目录资格≠策略合格；ABC按上市市场归类，非账户实时授权。/eligible 查看真实合格候选。']
    return '\n'.join(lines)
