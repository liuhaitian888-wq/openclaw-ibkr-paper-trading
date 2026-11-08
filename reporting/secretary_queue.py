"""Durable owner inbox and scheduled research; uncertain model runs never replay."""
from contextlib import closing
import json
from .agent_secretary import SecretaryArchive
from .incidents import IncidentStore
from .errors import redact

AUTHORITY='secretary:standing-authorization:20261107'
CONVERSATION='der-secretary'
AUTH_TEXT='用户授权：无新要求时自主提出研究课题、设计实验和测试；读取全部已登记业务数据库。交易门禁保持，禁止下单、撤单、修改保护单。日常研究与模型费用自行管理，只在用户明确边界或判断有风险时汇报；此条不代表已经购买任何资源。'


def initialize(archive):
    archive.append(AUTHORITY,CONVERSATION,origin='USER',kind='STANDING_AUTHORIZATION',payload={
        'text':AUTH_TEXT,'source':'User message 2026-11-07 and authorized continuation; faithful scope summary, not verbatim quote'})
    with closing(archive.connect()) as c,c:
        c.execute('CREATE TABLE IF NOT EXISTS secretary_received (instruction TEXT PRIMARY KEY, received_at REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS secretary_ack_checkpoint (instruction TEXT PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS secretary_checkpoints (run TEXT PRIMARY KEY, state TEXT NOT NULL, payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS secretary_cursor (id INTEGER PRIMARY KEY CHECK(id=1), next_update INTEGER NOT NULL)')


def accept_update(archive, update, config, *, armed_at):
    received=archive.clock()
    uid=update.get('update_id')
    if type(uid) is not int or uid<0:raise ValueError('Native update ID required')
    m=update.get('message',{});sender=m.get('from',{})
    native_chat=m.get('chat',{}).get('id')
    allowed=(config.get('owner_private_verified') is True
             and config.get('owner_private_chat_id')==config['owner_user_id']
             and native_chat==config['owner_user_id'] and m.get('chat',{}).get('type','private')=='private'
             and sender.get('id')==config['owner_user_id']
             and sender.get('is_bot') is False and not any(m.get(k) for k in ('sender_chat','forward_origin','forward_from','forward_from_chat','forward_date','via_bot'))
             and isinstance(m.get('text'),str) and 0<len(m['text'])<=4000
             and type(m.get('date')) is int and m['date']>=armed_at and type(m.get('message_id')) is int)
    if allowed:
        archive.append('telegram:'+str(native_chat)+':'+str(uid),CONVERSATION,origin='USER',kind='CONTROL_INSTRUCTION' if (m['text'].split() or [''])[0].split('@')[0] in ('/marketdata','/market_register','/market_check','/universe','/eligible','/watch','/work','/searchlog','/search','/start','/inbox','/event','/read','/notify','/preview','/report','/engineering','/ready','/holdings','/gate','/gate_apply','/gate_batch','/gate_confirm','/gate_help','/help','/gate_set','/qmax','/omax','/rmax','/smax','/gmax','/login','/login_assist','/focus','/intel') else 'CHAT_INSTRUCTION',payload={
            'text':redact(m['text']),'source':'Telegram native owner message','update_id':uid,
            'message_id':m['message_id'],'chat_id':native_chat,'timestamp':m['date']})
    with closing(archive.connect()) as c,c:
        c.execute('CREATE TABLE IF NOT EXISTS secretary_received (instruction TEXT PRIMARY KEY, received_at REAL NOT NULL)')
        if allowed:c.execute('INSERT OR IGNORE INTO secretary_received VALUES (?,?)',('telegram:'+str(native_chat)+':'+str(uid),received))
        c.execute('INSERT INTO secretary_cursor VALUES(1,?) ON CONFLICT(id) DO UPDATE SET next_update=max(next_update,excluded.next_update)',(uid+1,))
    return allowed


def cursor(archive):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT next_update FROM secretary_cursor WHERE id=1').fetchone()
    return row[0] if row else 0


def autonomous(archive, *, now):
    # A slot is an immutable occurrence, including after focus/policy changes.
    slot=int(now//21600)
    with closing(archive.connect()) as c:
        if c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',('autonomous:'+str(slot),)).fetchone():return False
    # Four opportunities/day; skipped slots never backfill. STARTED/UNKNOWN blocks autonomous spend.
    with closing(archive.connect()) as c:
        if c.execute("SELECT 1 FROM secretary_runs r WHERE state IN ('STARTED','UNKNOWN') AND NOT EXISTS(SELECT 1 FROM secretary_events e WHERE e.occurrence=r.occurrence||':reconciliation' AND e.kind='RUN_RECONCILIATION' AND e.origin='SYSTEM') LIMIT 1").fetchone():return False
    with closing(archive.connect()) as c:
        focus=c.execute("SELECT payload,parent FROM secretary_events WHERE kind='USER_FOCUS' AND origin='TOOL' ORDER BY rowid DESC LIMIT 1").fetchone()
    standing_focus={'text':json.loads(focus[0])['text'],'source_instruction':focus[1]} if focus else None
    slot=int(now//21600)
    return archive.append('autonomous:'+str(slot),CONVERSATION,origin='SYSTEM',kind='AUTONOMOUS_INSTRUCTION',parent=AUTHORITY,payload={
        'text':'自主研究本轮：先查档案避免重复。自行选择可证伪课题，读取数据库证据，运行已登记测试，报告实际结果、局限和下一步。无连续数据或费用版本时不得捏造策略收益。',
        'standing_focus':standing_focus,'slot':slot,'strategy_version':'research-policy-v1','cost_assumptions':'INCOMPLETE; no zero-fee default',
        'data_applicability':'Must establish point-in-time data and out-of-sample split before performance claims'})


def claim(archive, *, model, now):
    initialize(archive)
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        pending=c.execute("SELECT 1 FROM secretary_events e WHERE e.kind='CHAT_INSTRUCTION' AND NOT EXISTS (SELECT 1 FROM secretary_runs r WHERE r.instruction=e.occurrence) LIMIT 1").fetchone()
        budget_available=c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol' AND started_at>=?",(int(now//86400)*86400,)).fetchone()[0]<24
        resumed=c.execute("SELECT k.run,k.payload,r.instruction,e.payload,e.kind FROM secretary_checkpoints k JOIN secretary_runs r ON r.occurrence=k.run JOIN secretary_events e ON e.occurrence=r.instruction WHERE k.state='READY' AND r.state='STARTED' ORDER BY CASE e.origin WHEN 'USER' THEN 0 ELSE 1 END,e.rowid LIMIT 1").fetchone()
        if resumed and (not pending or not budget_available):
            c.execute("UPDATE secretary_checkpoints SET state='ACTIVE' WHERE run=?",(resumed[0],))
            data=json.loads(resumed[3]);data['autonomous']=resumed[4]=='AUTONOMOUS_INSTRUCTION'
            return dict(run=resumed[0],instruction=resumed[2],payload=data,model=model,checkpoint=json.loads(resumed[1]))
        # Daily paid-task bound includes all outcomes and starts, including UNKNOWN.
        if not budget_available:return None
        rows=c.execute("""SELECT e.occurrence,e.payload,e.kind FROM secretary_events e LEFT JOIN secretary_runs r ON r.instruction=e.occurrence
            WHERE e.kind IN ('CHAT_INSTRUCTION','AUTONOMOUS_INSTRUCTION') AND r.occurrence IS NULL
            ORDER BY CASE e.origin WHEN 'USER' THEN 0 ELSE 1 END,e.rowid LIMIT 25""").fetchall()
    for occurrence,payload,kind in rows:
        run=occurrence+':run'
        if archive.reserve_run(run,instruction=occurrence,model=model):
            data=json.loads(payload)
            data['autonomous']=kind=='AUTONOMOUS_INSTRUCTION'
            from .secretary_conversation import recent_context, owner_preferences
            return {'run':run,'instruction':occurrence,'payload':data,'model':model,
                    'conversation_context':recent_context(archive,occurrence,data),
                    'owner_preferences':owner_preferences(archive,occurrence)}
    return None


def enqueue_reply(archive, store, run, text, *, role='RESEARCH'):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()
    if row is None or row[0]!='SUCCEEDED':raise ValueError('Successful archived result required')
    with closing(archive.connect()) as c:
        metadata=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(run+':presentation',)).fetchone()
        result=c.execute('SELECT recorded_at FROM secretary_events WHERE occurrence=(SELECT result_event FROM secretary_runs WHERE occurrence=?)',(run,)).fetchone()
    encoded=json.dumps({'reason':redact(text[:3300]),'delivery_transport':'telegram','message_role':role,'queued_at':archive.clock(),'finished_at':result[0] if result else None,'run':run,**(json.loads(metadata[0]) if metadata else {})},ensure_ascii=False,sort_keys=True)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('secretary:'+run,encoded))


def reconcile_replies(archive, store):
    """Idempotent enqueue repairs the archive/outbox crash window; never HTTP replay."""
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT r.occurrence,e.payload FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.result_event WHERE r.state='SUCCEEDED' ORDER BY r.rowid DESC LIMIT 100").fetchall()
    for run,payload in rows:
        result=json.loads(payload)
        if isinstance(result.get('summary'),str):enqueue_reply(archive,store,run,result['summary'],role=result.get('response_mode','RESEARCH'))


def progress(store,run,stage,text):
    """Public activity milestones only; unique enqueue, no private reasoning stream."""
    if stage not in ('CLAIMED','FIRST_TOOL'):raise ValueError('Bounded public milestone required')
    payload=json.dumps({'reason':'处理进度｜'+text[:500]+'\n档案：'+run,'delivery_transport':'telegram','message_role':'PROGRESS'},ensure_ascii=False)
    with closing(store.connect()) as c,c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('secretary-progress:'+run+':'+stage,payload))


def checkpoint(archive,run,data):
    """Only acknowledged model/tool output may reach READY. ACTIVE/UNKNOWN never resume."""
    if (not isinstance(data,dict) or set(data)!={'turn','step','transcript','usage'}
            or type(data['turn']) is not int or not 1<=data['turn']<=2
            or type(data['step']) is not int or not 0<=data['step']<=8
            or not isinstance(data['transcript'],list) or not isinstance(data['usage'],list)):
        raise ValueError('Bounded acknowledged checkpoint required')
    encoded=json.dumps(data,ensure_ascii=False,allow_nan=False)
    if len(encoded)>50000:raise ValueError('Checkpoint too large')
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()!=('STARTED',):
            raise ValueError('Active run required')
        prior=c.execute('SELECT state,payload FROM secretary_checkpoints WHERE run=?',(run,)).fetchone()
        if prior and prior[0]=='READY':
            if prior[1]!=encoded:raise ValueError('Checkpoint conflict')
            return
        if prior and json.loads(prior[1])['turn']>=data['turn']:raise ValueError('Checkpoint must advance')
        c.execute("INSERT INTO secretary_checkpoints VALUES (?,'READY',?) ON CONFLICT(run) DO UPDATE SET state='READY',payload=excluded.payload",(run,encoded))


def reconcile_acknowledgements(archive,store):
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT e.occurrence,e.recorded_at FROM secretary_events e JOIN secretary_received v ON v.instruction=e.occurrence LEFT JOIN secretary_ack_checkpoint a ON a.instruction=e.occurrence WHERE a.instruction IS NULL AND e.kind='CHAT_INSTRUCTION' AND e.origin='USER' AND e.occurrence LIKE 'telegram:%' ORDER BY e.rowid LIMIT 100").fetchall()
    with closing(store.connect()) as c,c:
        for occurrence,saved in rows:
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('secretary-ack:'+occurrence,json.dumps(dict(reason='收到，正在处理。完整答复会在分析完成后发到这里。',delivery_transport='telegram',message_role='ACK',queued_at=saved,instruction=occurrence),ensure_ascii=False)))
    # Commit outbox first; crash before this checkpoint is repaired by INSERT OR IGNORE.
    with closing(archive.connect()) as c,c:
        c.executemany('INSERT OR IGNORE INTO secretary_ack_checkpoint VALUES (?)',[(x[0],) for x in rows])


def latency_sample(received,saved,claimed,finished,send_started,ack):
    points=[received,saved,claimed,finished,send_started,ack]
    names=['save','claim_wait','processing','delivery_wait','transport']
    return {**{name:(None if a is None or b is None else round(b-a,3)) for name,a,b in zip(names,points,points[1:])},
            'total':None if received is None or ack is None else round(ack-received,3)}
