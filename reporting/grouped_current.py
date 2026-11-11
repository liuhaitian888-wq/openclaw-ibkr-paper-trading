"""Exact operator authorization for fresh grouped recovery, never legacy replay.

This retires only the three already audited historical notification dependencies.
Each new current version keeps its own registered identity and transport outcome.
"""
from contextlib import closing
import json
import math

GROUPED_ACTION='GROUPED_FRESH_RECOVERY_CONTINUATION_V1'
SOURCE_THREAD='01a1c2f2-eed1-7ce1-9c20-22fad77ce6d2'
SOURCE_MESSAGE='01a1c326-572e-7e33-b5b3-2be24ab9056b'
USER_TEXT='那你跟通知工程师配合，把所有自动消息进群、故障和恢复合并发送真正改好，别只写文档。改完去 Telegram 看看，确认群里不刷屏，秘书私聊也不再收到这些自动告警。'


def initialize(store):
    with closing(store.connect()) as c,c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS notification_grouped_scopes(
          scope_id TEXT PRIMARY KEY,legacy_scope_id TEXT NOT NULL,authorized_at REAL NOT NULL,
          cutover_id INTEGER NOT NULL,installed_at REAL NOT NULL,
          authorization TEXT NOT NULL,authorization_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_grouped_current(
          notification_id INTEGER PRIMARY KEY,scope_id TEXT NOT NULL,incident_key TEXT NOT NULL,
          generation INTEGER NOT NULL,nonce TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
          state_sha256 TEXT NOT NULL,epoch TEXT NOT NULL,source_sha256 TEXT NOT NULL,registered_at REAL NOT NULL);
        ''')


def _scope(c,scope_id):
    from .notification_disposition import scope_valid,sha
    row=c.execute('SELECT legacy_scope_id,authorized_at,cutover_id,installed_at,authorization,authorization_sha256 FROM notification_grouped_scopes WHERE scope_id=?',(scope_id,)).fetchone()
    if row is None or sha(row[4])!=row[5]:return None
    auth=json.loads(row[4])
    if (not isinstance(auth,dict) or auth.get('action')!=GROUPED_ACTION or auth.get('origin')!='USER'
            or auth.get('source_thread')!=SOURCE_THREAD or auth.get('source_message')!=SOURCE_MESSAGE
            or not isinstance(auth.get('user_text'),str) or auth['user_text'].strip()!=USER_TEXT
            or not isinstance(auth.get('interpretation'),str) or not auth['interpretation'].strip()
            or not scope_valid(c,row[0])):return None
    install=c.execute("SELECT payload FROM incident_cursors WHERE source='automatic-policy:grouped-v1'").fetchone()
    if not install:return None
    install=json.loads(install[0])
    if (install.get('cutover_id')!=row[2] or install.get('installed_at')!=row[3]
            or type(row[2]) is not int or row[2]<0
            or any(type(x) not in (int,float) or not math.isfinite(x) for x in row[1:2]+row[3:4])
            or row[1]<row[3]):return None
    return row


def authorize_grouped_current(store,scope_id,legacy_scope_id,authorization):
    """Trusted operator only; not registered as a secretary/model write tool."""
    from .notification_disposition import encoded,sha
    if (not isinstance(scope_id,str) or not 1<=len(scope_id)<=150
            or not isinstance(legacy_scope_id,str) or not legacy_scope_id or not isinstance(authorization,dict)):
        raise PermissionError('Explicit operator grouped scope required')
    initialize(store)
    raw=encoded(authorization)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT legacy_scope_id,authorization FROM notification_grouped_scopes WHERE scope_id=?',(scope_id,)).fetchone()
        if old:
            if old!=(legacy_scope_id,raw) or not _scope(c,scope_id):raise PermissionError('Grouped scope changed')
            return scope_id
        install=c.execute("SELECT payload FROM incident_cursors WHERE source='automatic-policy:grouped-v1'").fetchone()
        if not install:raise PermissionError('Install grouped policy before authorizing its current-state scope')
        install=json.loads(install[0])
        c.execute('INSERT INTO notification_grouped_scopes VALUES (?,?,?,?,?,?,?)',
            (scope_id,legacy_scope_id,store.clock(),install['cutover_id'],install['installed_at'],raw,sha(raw)))
        if not _scope(c,scope_id):raise PermissionError('Exact current user authorization and unchanged legacy evidence required')
    return scope_id


def _source_proof(c,item,scope,now):
    from .automatic_notifications import _safe_unsent
    from .notification_disposition import encoded,sha
    p=item['payload'];sources=p.get('source_notification_ids',[]);refs=p.get('recovery_members',[])
    if not sources or not refs or len(refs)>1000:raise PermissionError('Bounded new source and recovery references required')
    ids=set(sources)
    for member in refs:
        if not isinstance(member,dict) or type(member.get('notification_id')) is not int or member['notification_id']<=scope[2]:
            raise PermissionError('Recovery member is not a new post-cutover occurrence')
        ids.add(member['notification_id'])
    evidence=[]
    for ident in sorted(ids):
        row=c.execute('SELECT incident_key,generation,kind,status,payload FROM notification_outbox WHERE id=?',(ident,)).fetchone()
        if (type(ident) is not int or ident<=scope[2] or row is None or not row[0].startswith('paper-safety:')
                or row[2]=='AUTOMATIC_STATUS' or row[3]!='SUPPRESSED' or not _safe_unsent(c,ident)):
            raise PermissionError('Historical, attempted or changed source cannot support grouped recovery')
        source=json.loads(row[4]);stamp=source.get('queued_at')
        if type(stamp) not in (int,float) or not math.isfinite(stamp) or not scope[3]<=stamp<=now:
            raise PermissionError('Fresh occurrence provenance missing')
        if ident in sources:
            mapping=c.execute('SELECT disposition,payload_sha256,aggregate_id FROM automatic_notification_sources WHERE notification_id=?',(ident,)).fetchone()
            if mapping!=('grouped',sha(row[4]),item['id']):raise PermissionError('Source projection identity changed')
        evidence.append([ident,*row])
    return sha(encoded(evidence))


def register_grouped_current(store,c,item,scope_id):
    """Caller owns the transaction; exact registration, never modifies old rows."""
    from .automatic_notifications import valid
    from .notification_disposition import encoded,sha,proof
    now=store.clock();p=item['payload'];scope=_scope(c,scope_id)
    if (not scope or item['kind']!='AUTOMATIC_STATUS' or p.get('family')!='broker'
            or p.get('phase')!='RECOVERED' or item['id']<=scope[2]
            or not valid(store,item,now,connection=c)):
        raise PermissionError('Registered stable fresh current broker recovery required')
    state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
    source_sha=_source_proof(c,item,scope,now)
    values=(scope_id,item['incident_key'],item['generation'],p['version_nonce'],
            sha(encoded(p)),proof(state,now),state['epoch'],source_sha)
    old=c.execute('SELECT scope_id,incident_key,generation,nonce,payload_sha256,state_sha256,epoch,source_sha256 FROM notification_grouped_current WHERE notification_id=?',(item['id'],)).fetchone()
    if old:
        if old!=values:raise PermissionError('Current grouped registration changed')
        return item['id']
    c.execute('INSERT INTO notification_grouped_current VALUES (?,?,?,?,?,?,?,?,?,?)',(item['id'],*values,now))
    c.execute('INSERT INTO notification_disposition_events(scope_id,notification_id,action,recorded_at,evidence) VALUES (?,?,?,?,?)',
              (scope_id,item['id'],GROUPED_ACTION,now,encoded({'legacy_scope_id':scope[0],'new_source_ids':p['source_notification_ids'],
              'payload_sha256':values[4],'source_sha256':source_sha,'original_outcomes':'UNKNOWN_UNCHANGED_NO_REPLAY'})))
    return item['id']


def grouped_current_valid(store,c,item,now):
    from .automatic_notifications import valid
    from .notification_disposition import encoded,sha,proof
    if item['kind']!='AUTOMATIC_STATUS' or not valid(store,item,now,connection=c):return False
    row=c.execute('SELECT scope_id,incident_key,generation,nonce,payload_sha256,state_sha256,epoch,source_sha256,registered_at FROM notification_grouped_current WHERE notification_id=?',(item['id'],)).fetchone()
    if not row:return False
    scope=_scope(c,row[0]);p=item['payload']
    if (not scope or p.get('family')!='broker' or p.get('phase')!='RECOVERED'
            or row[1:5]!=(item['incident_key'],item['generation'],p['version_nonce'],sha(encoded(p)))
            or not scope[1]<=row[8]<=now):return False
    if c.execute("""SELECT 1 FROM notification_outbox WHERE status IN ('STARTED','UNKNOWN')
      AND id!=? AND incident_key LIKE 'paper-safety:protection:%' AND id NOT IN (1270,1271,1272) LIMIT 1""",(item['id'],)).fetchone():return False
    if c.execute("""SELECT 1 FROM notification_outbox WHERE incident_key=? AND id<? AND status NOT IN
      ('SMTP_ACCEPTED','FEISHU_ACCEPTED','TELEGRAM_ACCEPTED','SUPERSEDED','NOT_SENT_EXHAUSTED','SUPPRESSED') LIMIT 1""",(item['incident_key'],item['id'])).fetchone():return False
    try:
        state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
        return (proof(state,now)==row[5] and state['epoch']==row[6]
                and _source_proof(c,item,scope,now)==row[7])
    except (PermissionError,ValueError,TypeError):return False


def eligible_grouped_current_ids(store,c,now):
    rows=c.execute("SELECT n.id,n.incident_key,n.generation,n.kind,n.payload FROM notification_grouped_current g JOIN notification_outbox n ON n.id=g.notification_id WHERE n.status='PENDING' ORDER BY n.id DESC LIMIT 10").fetchall()
    result=[]
    for ident,key,generation,kind,raw in rows:
        item=dict(id=ident,incident_key=key,generation=generation,kind=kind,payload=json.loads(raw))
        if grouped_current_valid(store,c,item,now):result.append(ident)
    return tuple(result)


def register_authorized_pending(store,c,group):
    if group!='broker':return
    scope=c.execute('SELECT scope_id FROM notification_grouped_scopes ORDER BY authorized_at DESC LIMIT 1').fetchone()
    if not scope:return
    rows=c.execute("SELECT id,incident_key,generation,kind,payload FROM notification_outbox WHERE incident_key='automatic-status:broker' AND status='PENDING' AND json_extract(payload,'$.phase')='RECOVERED' ORDER BY id DESC LIMIT 1").fetchall()
    for ident,key,generation,kind,raw in rows:
        try:register_grouped_current(store,c,dict(id=ident,incident_key=key,generation=generation,kind=kind,payload=json.loads(raw)),scope[0])
        except PermissionError:pass  # No exception authorization: original barriers remain.
