"""Durable bounded broker-query mailbox; only the existing broker owner executes it."""
from contextlib import closing
import hashlib
import json
import time

SECTIONS=frozenset(('account','positions','cash','orders','executions','quotes'))
AREAS=SECTIONS|{'snapshot'}


def initialize(archive):
    with closing(archive.connect()) as c,c:
        c.execute('''CREATE TABLE IF NOT EXISTS secretary_broker_queries(
            id TEXT PRIMARY KEY, run TEXT NOT NULL, request TEXT NOT NULL,
            state TEXT NOT NULL, queued REAL NOT NULL, started REAL, finished REAL,
            result TEXT, UNIQUE(run,id))''')


def result(archive,identity):
    if not isinstance(identity,str) or not identity.startswith('broker-query:') or len(identity)!=77:
        raise ValueError('Registered broker query identity required')
    with closing(archive.connect()) as c:
        row=c.execute('SELECT state,queued,started,finished,result FROM secretary_broker_queries WHERE id=?',(identity,)).fetchone()
    if row is None:return {'state':'NOT_FOUND','id':identity}
    if row[0]=='READY' and archive.clock()-row[1]>30:
        with closing(archive.connect()) as c,c:
            c.execute("UPDATE secretary_broker_queries SET state='UNAVAILABLE',finished=?,result=? WHERE id=? AND state='READY'",
                (archive.clock(),json.dumps({'reason':'Broker owner unavailable before query deadline'}),identity))
        return result(archive,identity)
    return dict(id=identity,state=row[0],queued_at=row[1],started_at=row[2],finished_at=row[3],
                result=json.loads(row[4]) if row[4] else None,grants_trading_permission=False)


def submit(archive,request,*,run,step,wait_seconds=8):
    if (request.get('area') not in AREAS or set(request)-{'name','area','symbols','sections','source'}
            or type(step) is not int or not 1<=step<=12 or not isinstance(run,str) or not run
            or not 0<=wait_seconds<=8):raise ValueError('Bounded registered broker query required')
    symbols=request.get('symbols',[])
    if not isinstance(symbols,list) or len(symbols)>5 or any(not isinstance(s,str) or not 1<=len(s)<=16 or not s.replace('.','').isalnum() for s in symbols):
        raise ValueError('At most five explicit symbol identifiers required')
    body={'area':request['area'],'symbols':symbols}
    if 'sections' in request:
        sections=request['sections']
        if (request['area']!='snapshot' or not isinstance(sections,list) or not 1<=len(sections)<=6
                or any(not isinstance(x,str) or x not in SECTIONS for x in sections)
                or len(set(sections))!=len(sections)):
            raise ValueError('Snapshot requires one to six distinct registered sections')
        body['sections']=sections
    body=json.dumps(body,sort_keys=True)
    identity='broker-query:'+hashlib.sha256((run+':'+str(step)).encode()).hexdigest()
    initialize(archive)
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        prior=c.execute('SELECT request FROM secretary_broker_queries WHERE id=?',(identity,)).fetchone()
        if prior and prior[0]!=body:raise ValueError('Broker query identity reused with different content')
        if not prior:
            if c.execute("SELECT count(*) FROM secretary_broker_queries WHERE state IN ('READY','STARTED')").fetchone()[0]>=12:
                return {'state':'BUSY','reason':'Bounded broker query queue full'}
            c.execute('INSERT INTO secretary_broker_queries(id,run,request,state,queued) VALUES (?,?,?,\'READY\',?)',
                      (identity,run,body,archive.clock()))
    deadline=time.monotonic()+wait_seconds
    while True:
        value=result(archive,identity)
        if value['state'] not in ('READY','STARTED') or time.monotonic()>=deadline:return value
        time.sleep(min(.1,max(0,deadline-time.monotonic())))
