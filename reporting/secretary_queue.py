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
        c.execute('CREATE TABLE IF NOT EXISTS secretary_cursor (id INTEGER PRIMARY KEY CHECK(id=1), next_update INTEGER NOT NULL)')


def accept_update(archive, update, config, *, armed_at):
    uid=update.get('update_id')
    if type(uid) is not int or uid<0:raise ValueError('Native update ID required')
    m=update.get('message',{});sender=m.get('from',{})
    allowed=(m.get('chat',{}).get('id')==config['chat_id'] and sender.get('id')==config['owner_user_id']
             and sender.get('is_bot') is False and not any(m.get(k) for k in ('sender_chat','forward_origin','via_bot'))
             and isinstance(m.get('text'),str) and 0<len(m['text'])<=4000
             and type(m.get('date')) is int and m['date']>=armed_at and type(m.get('message_id')) is int)
    if allowed:
        archive.append('telegram:'+str(config['chat_id'])+':'+str(uid),CONVERSATION,origin='USER',kind='CONTROL_INSTRUCTION' if (m['text'].split() or [''])[0].split('@')[0] in ('/gate','/gate_apply','/login','/login_assist') else 'CHAT_INSTRUCTION',payload={
            'text':redact(m['text']),'source':'Telegram native owner message','update_id':uid,
            'message_id':m['message_id'],'timestamp':m['date']})
    with closing(archive.connect()) as c,c:
        c.execute('INSERT INTO secretary_cursor VALUES(1,?) ON CONFLICT(id) DO UPDATE SET next_update=max(next_update,excluded.next_update)',(uid+1,))
    return allowed


def cursor(archive):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT next_update FROM secretary_cursor WHERE id=1').fetchone()
    return row[0] if row else 0


def autonomous(archive, *, now):
    # Four opportunities/day; skipped slots never backfill. STARTED/UNKNOWN blocks autonomous spend.
    with closing(archive.connect()) as c:
        if c.execute("SELECT 1 FROM secretary_runs r WHERE state IN ('STARTED','UNKNOWN') AND NOT EXISTS(SELECT 1 FROM secretary_events e WHERE e.occurrence=r.occurrence||':reconciliation' AND e.kind='RUN_RECONCILIATION' AND e.origin='SYSTEM') LIMIT 1").fetchone():return False
    slot=int(now//21600)
    return archive.append('autonomous:'+str(slot),CONVERSATION,origin='SYSTEM',kind='AUTONOMOUS_INSTRUCTION',parent=AUTHORITY,payload={
        'text':'自主研究本轮：先查档案避免重复。自行选择可证伪课题，读取数据库证据，运行已登记测试，报告实际结果、局限和下一步。无连续数据或费用版本时不得捏造策略收益。',
        'slot':slot,'strategy_version':'research-policy-v1','cost_assumptions':'INCOMPLETE; no zero-fee default',
        'data_applicability':'Must establish point-in-time data and out-of-sample split before performance claims'})


def claim(archive, *, model, now):
    with closing(archive.connect()) as c:
        # Daily paid-task bound includes all outcomes and starts, including UNKNOWN.
        if c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol' AND started_at>=?",(int(now//86400)*86400,)).fetchone()[0]>=24:return None
        rows=c.execute("""SELECT e.occurrence,e.payload FROM secretary_events e LEFT JOIN secretary_runs r ON r.instruction=e.occurrence
            WHERE e.kind IN ('CHAT_INSTRUCTION','AUTONOMOUS_INSTRUCTION') AND r.occurrence IS NULL
            ORDER BY CASE e.origin WHEN 'USER' THEN 0 ELSE 1 END,e.rowid LIMIT 25""").fetchall()
    for occurrence,payload in rows:
        run=occurrence+':run'
        if archive.reserve_run(run,instruction=occurrence,model=model):
            return {'run':run,'instruction':occurrence,'payload':json.loads(payload),'model':model}
    return None


def enqueue_reply(archive, store, run, text):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()
    if row is None or row[0]!='SUCCEEDED':raise ValueError('Successful archived result required')
    encoded=json.dumps({'reason':redact(text[:3300]),'delivery_transport':'telegram'},ensure_ascii=False,sort_keys=True)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('secretary:'+run,encoded))


def reconcile_replies(archive, store):
    """Idempotent enqueue repairs the archive/outbox crash window; never HTTP replay."""
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT r.occurrence,e.payload FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.result_event WHERE r.state='SUCCEEDED' ORDER BY r.rowid DESC LIMIT 100").fetchall()
    for run,payload in rows:
        result=json.loads(payload)
        if isinstance(result.get('summary'),str):enqueue_reply(archive,store,run,result['summary'])
