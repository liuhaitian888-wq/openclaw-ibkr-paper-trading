"""Report delivery evidence in the shared fault journal; never sends or replays."""
from contextlib import closing
from datetime import datetime,timezone,time
import hashlib,json
from zoneinfo import ZoneInfo

BJ=ZoneInfo('Asia/Shanghai');BERLIN=ZoneInfo('Europe/Berlin')


def evidence(c,row):
    identifier,key,kind,status,payload=row
    try:
        data=json.loads(payload)
        if not isinstance(data,dict):raise ValueError('Report payload object required')
        receipt=c.execute('SELECT payload FROM notification_receipts WHERE notification_id=?',(identifier,)).fetchone()
        receipt=json.loads(receipt[0]) if receipt else None
    except (ValueError,TypeError):
        return {'notification_id':identifier,'incident_key':key,'kind':kind,'status':'EVIDENCE_INVALID','raw_status':status,
                'telegram_server_accepted':False,'automatic_replay_allowed':False,'phone_notification_verified':False}
    confirmed=(status=='TELEGRAM_ACCEPTED' and isinstance(receipt,dict) and receipt.get('transport')=='telegram'
        and type(receipt.get('chat_id')) is int and receipt['chat_id']!=0 and bool(receipt.get('message_ids'))
        and all(type(i) is int and i>0 for i in receipt['message_ids']) and len(receipt.get('server_dates',[]))==len(receipt['message_ids']))
    return {'notification_id':identifier,'incident_key':key,'kind':kind,'status':status,'telegram_server_accepted':bool(confirmed),
        'daily_report_included':'DAILY' in data.get('included_reports',[]),
        'content_state':'DAILY_INCLUDED' if 'DAILY' in data.get('included_reports',[]) else 'MISSING_DAILY_ALERT_ONLY',
        'daily_report_server_accepted':bool(confirmed and 'DAILY' in data.get('included_reports',[])),
        'scheduled_at':data.get('scheduled_at'),'queued_at':data.get('queued_at'),'included_reports':data.get('included_reports',[]),
        'missing_reports':data.get('missing_reports',[]),'snapshot_current':data.get('snapshot_current'),
        'retry_of':data.get('retry_of'),'reconciliation_review':data.get('reconciliation_review'),
        'receipt':receipt,'phone_notification_verified':False,'automatic_replay_allowed':False}


def record_status(store,now):
    """Existing sender calls this at most once/minute. Same evidence survives restart without duplication."""
    if now.tzinfo is None:raise ValueError('Timezone-aware observation required')
    with closing(store.connect()) as c,c:
        c.execute('CREATE TABLE IF NOT EXISTS report_delivery_status (notification_id INTEGER PRIMARY KEY,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,observed_at TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS report_delivery_events (id INTEGER PRIMARY KEY,notification_id INTEGER NOT NULL,fingerprint TEXT NOT NULL UNIQUE,observed_at TEXT NOT NULL,payload TEXT NOT NULL)')
        rows=c.execute("SELECT id,incident_key,kind,status,payload FROM notification_outbox WHERE kind IN ('REPORT_BUNDLE','REPORT_SUPPLEMENT') ORDER BY id DESC LIMIT 40").fetchall()
        changed=0
        for row in rows:
            value=evidence(c,row);encoded=json.dumps(value,ensure_ascii=False,sort_keys=True)
            fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
            prior=c.execute('SELECT fingerprint FROM report_delivery_status WHERE notification_id=?',(row[0],)).fetchone()
            if prior and prior[0]==fingerprint:continue
            c.execute('INSERT OR IGNORE INTO report_delivery_events(notification_id,fingerprint,observed_at,payload) VALUES(?,?,?,?)',(row[0],fingerprint,now.isoformat(),encoded))
            c.execute('INSERT OR REPLACE INTO report_delivery_status VALUES(?,?,?,?)',(row[0],fingerprint,encoded,now.isoformat()))
            # A delivery observation belongs in the common journal without inventing an incident or clearing REPORT health.
            c.execute('INSERT INTO module_events(payload) VALUES(?)',(json.dumps({'module':'REPORT','event':'REPORT_DELIVERY_STATUS','observed_at':now.isoformat(),'delivery_evidence':value},ensure_ascii=False),))
            changed+=1
    return changed


def display(store,now):
    if now.tzinfo is None:raise ValueError('Timezone-aware query required')
    day=now.astimezone(BJ).date();planned=datetime.combine(day,time(9),BJ)
    lines=['日报发送状态｜'+day.isoformat(),'计划：'+planned.strftime('%H:%M 北京时间')+' / '+planned.astimezone(BERLIN).strftime('%H:%M 柏林时间')]
    key='financial-reports:'+day.isoformat()
    with closing(store.connect()) as c:
        rows=c.execute("SELECT id,incident_key,kind,status,payload FROM notification_outbox WHERE (incident_key=? OR kind='REPORT_SUPPLEMENT' OR json_extract(payload,'$.retry_of') IN (SELECT id FROM notification_outbox WHERE incident_key=?)) AND kind IN ('REPORT_BUNDLE','REPORT_SUPPLEMENT') ORDER BY id DESC LIMIT 40",(key,key)).fetchall()
        selected=[]
        for row in rows:
            item=evidence(c,row);queued=item.get('queued_at')
            if row[1]!=key and not (type(queued) in (int,float) and datetime.fromtimestamp(queued,BJ).date()==day):continue
            selected.append(item)
        initial=next((x for x in selected if x['incident_key']==key and x['kind']=='REPORT_BUNDLE'),None)
        chosen=([initial] if initial else [])+[x for x in selected if x is not initial][:3]
    if not initial:lines.append('原定日报：尚无排队记录'+('（尚未到计划时间）' if now<planned else '；需检查生成和排队日志'))
    for item in chosen:
        label='原定日报' if item is initial else '补发/修正版'
        if item.get('content_state')=='MISSING_DAILY_ALERT_ONLY':label+='（仅缺报告警，未附今日日报）'
        if item['telegram_server_accepted']:
            receipt=item['receipt'];times=[]
            for raw in receipt['server_dates']:
                try:
                    at=datetime.fromisoformat(raw.replace('Z','+00:00'))
                    times.append(at.astimezone(BJ).strftime('%H:%M:%S 北京')+' / '+at.astimezone(BERLIN).strftime('%H:%M:%S 柏林'))
                except (ValueError,TypeError):times.append('回执时间待核验')
            lines.append(label+'：Telegram已接收，'+'；'.join(times)+'，消息 '+','.join(str(i) for i in receipt['message_ids']))
        else:lines.append(label+'：'+{'SUPPRESSED':'按通知偏好静音，未发送','PENDING':'待发送','STARTED':'正在发送/等待回执','UNKNOWN':'结果未知，须对账，禁止自动重发','NOT_SENT_EXHAUSTED':'未发送，重试已停止','TELEGRAM_ACCEPTED':'状态为已接收，但原生回执待核验'}.get(item['status'],item['status']))
    lines.append('发送记录已接入统一日志；服务端接收不等于手机弹窗。查询不触发补发。')
    return '\n'.join(lines)
