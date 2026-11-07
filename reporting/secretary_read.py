"""Bounded read access to every registered business DB, without broker transport."""
from contextlib import closing
import json
import math
import operator
import sqlite3
import time
from .database_console import DATABASES, contained, collect as snapshot
from .errors import redact

REGISTRY = {row[0]: row[1] for row in DATABASES}
FUNCTIONS = frozenset('count sum avg min max total coalesce ifnull nullif abs round length substr substring lower upper trim ltrim rtrim date time datetime strftime julianday unixepoch typeof json_extract json_valid json_type like glob'.split())


def query(root, database, sql, parameters=(), *, limit=100, budget=.1):
    if database not in REGISTRY:
        raise ValueError('Registered database required')
    if (not isinstance(sql, str) or not 0 < len(sql) <= 8000
            or type(limit) is not int or not 1 <= limit <= 100
            or not .001 <= budget <= .1
            or not isinstance(parameters, (list, tuple)) or len(parameters) > 100
            or any(type(v) not in (str, int, float, type(None)) or isinstance(v, str) and len(v)>2048 for v in parameters)):
        raise ValueError('Bounded SQL, parameters, rows and deadline required')
    path = contained(root, database)
    if not path.is_file():
        return {'state': 'NOT_CREATED', 'database': database}
    deadline = time.monotonic()+budget
    def authorize(action, first, second, *_):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and (second or '').lower() in FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.02)) as c:
        c.execute('PRAGMA query_only=ON')
        c.enable_load_extension(False)
        c.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
        c.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8000)
        c.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        c.set_authorizer(authorize)
        cursor = c.execute('SELECT * FROM ('+sql.strip().rstrip(';')+') LIMIT ?', (*parameters, limit+1))
        rows=cursor.fetchmany(limit+1)
        columns=[d[0] for d in cursor.description]
    cleaned=[];size=0;truncated=len(rows)>limit
    for row in rows[:limit]:
        record={name: ('[BINARY OMITTED]' if isinstance(v,bytes) else v[:2048] if isinstance(v,str) else v) for name,v in zip(columns,row)}
        record=redact(record)
        encoded=json.dumps(record,ensure_ascii=False,allow_nan=False)
        size+=len(encoded.encode())
        if size>50_000:truncated=True;break
        cleaned.append(record)
    return {'state':'READ_ONLY_RESULT','database':database,'rows':cleaned,'truncated':truncated,
            'consistency':'single query snapshot; no cross-database atomicity','observed_at':time.time()}


def tool(root, request):
    if not isinstance(request,dict):raise ValueError('Structured tool request required')
    name=request.get('name')
    if name=='databases':return snapshot(root)
    if name=='schema':
        return query(root,request['database'],"SELECT name,sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
    if name=='query':return query(root,request['database'],request['sql'],request.get('parameters',[]))
    if name=='hypothesis_test':
        operators={'eq':operator.eq,'lt':operator.lt,'le':operator.le,'gt':operator.gt,'ge':operator.ge}
        comparison=request.get('comparison');expected=request.get('expected')
        if comparison not in operators or type(expected) not in (int,float) or not math.isfinite(expected):
            raise ValueError('Explicit finite numerical assertion required')
        evidence=query(root,request['database'],request['sql'],request.get('parameters',[]),limit=2)
        rows=evidence.get('rows',[])
        if evidence.get('truncated') or len(rows)!=1 or len(rows[0])!=1:
            return {'result':'INCONCLUSIVE','evidence':evidence}
        actual=next(iter(rows[0].values()))
        if type(actual) not in (int,float) or not math.isfinite(actual):
            return {'result':'INCONCLUSIVE','evidence':evidence}
        return {'experiment':'sql-scalar-assertion-v1','result':'SUPPORTED' if operators[comparison](actual,expected) else 'FALSIFIED',
                'actual':actual,'comparison':comparison,'expected':expected,'evidence':evidence,
                'scope':'Single asserted numerical condition; not statistical significance or profitability proof'}
    if name=='coverage_test':
        # Fixed reproducible experiment: data sufficiency, never a claimed strategy backtest.
        return {'experiment':'market-data-sufficiency-v1','hypothesis':'A reproducible long-horizon net-return backtest has adequate persisted inputs',
                'result':'NOT_ESTABLISHED','reason':'Callback counts and rolling in-memory bars do not establish continuous point-in-time OHLCV.',
                'required':['versioned dataset and timezone','gap and adjustment audit','point-in-time universe','commission schedule version and provenance','slippage sensitivity','frozen train/validation/out-of-sample split'],
                'fees':'INCOMPLETE unless versioned assumptions supplied; never default zero',
                'snapshot':snapshot(root)}
    raise PermissionError('Tool not registered; shell, file writes and broker operations unavailable')
