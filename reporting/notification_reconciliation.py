"""Append-only delivery evidence and deterministic, bounded recovery decisions.

Absence is never non-delivery proof. Only a locally recorded pre-wire failure or
a typed Telegram rejection of a SEND permits one linked retry. Model prose has
no authorization role. The existing sender remains the only transport owner.
"""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import math

VERSION='notification-reconciliation-v1'


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))
def fingerprint(value):return hashlib.sha256(encode(value).encode()).hexdigest()


def initialize(store):
    with closing(store.connect()) as c,c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS notification_attempts (
          id INTEGER PRIMARY KEY, notification_id INTEGER NOT NULL, created_at REAL NOT NULL,
          envelope TEXT NOT NULL, envelope_sha256 TEXT NOT NULL, policy_version TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS notification_attempt_lookup ON notification_attempts(notification_id,id);
        CREATE TABLE IF NOT EXISTS notification_attempt_events (
          id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL, observed_at REAL NOT NULL,
          stage TEXT NOT NULL, evidence TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS notification_attempt_event_lookup ON notification_attempt_events(attempt_id,id);
        CREATE TABLE IF NOT EXISTS notification_reviews (
          id TEXT PRIMARY KEY, notification_id INTEGER NOT NULL, observed_at REAL NOT NULL,
          decision TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, evidence TEXT NOT NULL, policy_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_retry_authorizations (
          notification_id INTEGER PRIMARY KEY, review_id TEXT NOT NULL,
          evidence_sha256 TEXT NOT NULL, authorized_at REAL NOT NULL, retry_id INTEGER NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS notification_review_notices (
          notification_id INTEGER NOT NULL, notice_kind TEXT NOT NULL, outbox_id INTEGER NOT NULL,
          PRIMARY KEY(notification_id,notice_kind));
        ''')


def begin_attempt(store,item):
    # Original exact envelope retained in private state; no credential config.
    envelope={k:item[k] for k in ('id','incident_key','generation','kind','payload')}
    with closing(store.connect()) as c,c:
        cur=c.execute('INSERT INTO notification_attempts(notification_id,created_at,envelope,envelope_sha256,policy_version) VALUES(?,?,?,?,?)',
                      (item['id'],store.clock(),encode(envelope),fingerprint(envelope),VERSION))
        return cur.lastrowid


def event(store,attempt_id,stage,evidence=None):
    if stage not in ('PREFLIGHT_FAILED','WIRE_START','ACCEPTED','UNKNOWN','REJECTED','SUPPRESSED','BLOCKED'):
        raise ValueError('Registered delivery stage required')
    with closing(store.connect()) as c,c:
        c.execute('INSERT INTO notification_attempt_events(attempt_id,observed_at,stage,evidence) VALUES(?,?,?,?)',
                  (attempt_id,store.clock(),stage,encode(evidence or {})))


def _receipt_valid(receipt,wire=None):
    if not isinstance(receipt,dict) or receipt.get('transport')!='telegram':return False
    target=receipt.get('chat_id');ids=receipt.get('message_ids');dates=receipt.get('server_dates')
    if (type(target) is not int or target==0 or not isinstance(ids,list) or not 1<=len(ids)<=3
            or any(type(x) is not int or x<=0 for x in ids) or len(set(ids))!=len(ids)
            or not isinstance(dates,list) or len(dates)!=len(ids)):return False
    try:
        if any(datetime.fromisoformat(x).tzinfo is None for x in dates):return False
    except (ValueError,TypeError):return False
    return wire is None or (target==wire.get('chat_id') and len(ids)==wire.get('message_count'))


def _evidence(c,ident):
    row=c.execute('SELECT incident_key,generation,kind,payload,status FROM notification_outbox WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('Notification not found')
    attempts=[]
    for aid,created,envelope,sha in c.execute('SELECT id,created_at,envelope,envelope_sha256 FROM notification_attempts WHERE notification_id=? ORDER BY id',(ident,)).fetchall():
        events=[dict(id=x[0],at=x[1],stage=x[2],evidence=json.loads(x[3])) for x in c.execute('SELECT id,observed_at,stage,evidence FROM notification_attempt_events WHERE attempt_id=? ORDER BY id',(aid,))]
        attempts.append(dict(id=aid,created_at=created,envelope_sha256=sha,events=events))
    receipt=c.execute('SELECT payload FROM notification_receipts WHERE notification_id=?',(ident,)).fetchone()
    delivery=c.execute('SELECT attempt_started_at,ack_received_at,status FROM notification_delivery WHERE notification_id=?',(ident,)).fetchone()
    try:receipt=json.loads(receipt[0]) if receipt else None
    except (ValueError,TypeError):receipt={'malformed':True}
    return dict(notification_id=ident,incident_key=row[0],generation=row[1],kind=row[2],payload_sha256=fingerprint(json.loads(row[3])),
                status=row[4],attempts=attempts,receipt=receipt,legacy_delivery=list(delivery) if delivery else None),json.loads(row[3])


def _classify(evidence):
    attempts=evidence['attempts'];last=attempts[-1] if attempts else None
    wires=[x['evidence'] for a in attempts for x in a['events'] if x['stage']=='WIRE_START']
    wire=wires[-1] if wires else None
    accepted=[x['evidence'].get('receipt') for a in attempts for x in a['events'] if x['stage']=='ACCEPTED']
    receipts=accepted+([evidence['receipt']] if evidence['receipt'] is not None else [])
    if receipts:
        if any(not _receipt_valid(r,wire) for r in receipts):return 'UNRESOLVED'
        identities={fingerprint([r['chat_id'],r['message_ids'],r['server_dates']]) for r in receipts}
        return 'ALREADY_ACCEPTED' if len(identities)==1 else 'UNRESOLVED'
    if last:
        stages=[x['stage'] for x in last['events']]
        prior_wires=[a for a in attempts[:-1] if any(x['stage']=='WIRE_START' for x in a['events'])]
        if not prior_wires and stages and stages[-1]=='PREFLIGHT_FAILED' and 'WIRE_START' not in stages and evidence['legacy_delivery'] is None:
            return 'PROVEN_UNSENT'
        if stages and stages[-1]=='REJECTED' and wire and wire.get('action')=='SEND':
            return 'PROVEN_UNSENT'
    return 'UNRESOLVED'


def assess(store,notification_id):
    """Bounded local assessment, append once per changed evidence; no network/model."""
    initialize(store)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        evidence,_=_evidence(c,notification_id);decision=_classify(evidence);sha=fingerprint(evidence)
        review=fingerprint([VERSION,notification_id,sha,decision])
        c.execute('INSERT OR IGNORE INTO notification_reviews VALUES(?,?,?,?,?,?,?)',
                  (review,notification_id,store.clock(),decision,sha,encode(evidence),VERSION))
    return dict(review_id=review,notification_id=notification_id,decision=decision,evidence_fingerprint=sha,
                evidence=evidence,model_assessment='NOT_REQUIRED_FOR_DETERMINISTIC_PROOF',grants_trading_permission=False)


def inspect(root,notification_id):
    """Read-only model tool: never creates reviews, retries or transport calls."""
    import sqlite3
    from pathlib import Path
    path=Path(root)/'runtime/recovery.sqlite3'
    if type(notification_id) is not int or notification_id<=0:raise ValueError('Positive event ID required')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as c:
        tables={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'notification_attempts' not in tables:return {'decision':'UNRESOLVED','reason':'Legacy delivery without per-attempt evidence','notification_id':notification_id}
        evidence,_=_evidence(c,notification_id)
    return dict(decision=_classify(evidence),evidence=evidence,grants_trading_permission=False,read_only=True)


def authorize_retry(store,review_id,evidence_fingerprint,config,*,dependency_verified):
    """One retry budget per original occurrence. Does not reset the original row.

    The sender must supply fresh native destination proof, then recheck all bytes
    and expiry here. A boolean model output is never passed to this function.
    """
    from .notification_access import decision
    from .incident_telegram import report_bytes
    from pathlib import Path
    initialize(store)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT notification_id,decision,evidence_sha256 FROM notification_reviews WHERE id=?',(review_id,)).fetchone()
        if row is None or row[1]!='PROVEN_UNSENT' or row[2]!=evidence_fingerprint or dependency_verified is not True:
            raise PermissionError('Fresh exact proven-unsent review and native dependency proof required')
        ident=row[0];evidence,payload=_evidence(c,ident)
        if fingerprint(evidence)!=evidence_fingerprint or _classify(evidence)!='PROVEN_UNSENT':raise PermissionError('Evidence changed')
        if c.execute('SELECT 1 FROM notification_retry_authorizations WHERE notification_id=?',(ident,)).fetchone():return None
        if evidence['status'] not in ('UNKNOWN','NOT_SENT_EXHAUSTED'):return None
        if payload.get('retry_of') is not None or payload.get('private_notice') is True:return None
        now=store.clock();queued=payload.get('queued_at');expiry=payload.get('expires_at',queued+600 if type(queued) in (int,float) else None)
        if (type(queued) not in (int,float) or type(expiry) not in (int,float) or not math.isfinite(expiry)
                or not 0<=now-queued<=600 or now>=expiry):raise PermissionError('Original content expired or freshness unknown')
        rejection=next((e['evidence'] for e in reversed(evidence['attempts'][-1]['events']) if e['stage']=='REJECTED'),None)
        if rejection is not None:
            until=rejection.get('retry_after_until')
            if (rejection.get('error_class')!='RetryAfter' or type(until) not in (int,float)
                    or not math.isfinite(until) or now<until):
                raise PermissionError('Rejected request requires proven root correction or elapsed server retry window')
        item=dict(id=ident,kind=evidence['kind'],incident_key=evidence['incident_key'],generation=evidence['generation'],payload=payload)
        if not evidence['attempts'] or evidence['attempts'][-1]['envelope_sha256']!=fingerprint(item):
            raise PermissionError('Original immutable envelope changed')
        route=decision(item,config)
        if route['audience']=='hold':raise PermissionError('Audience decision pending')
        from .notification_center import render
        view=render(item,config,now)
        if len(view['text'])>(800 if payload.get('png_artifacts') else 3700):raise PermissionError('Caption not valid for bounded retry explanation')
        # Resolve from the immutable configured state root, never from a payload path.
        report_bytes(item,Path(config['_report_root']))
        for a in evidence['attempts']:
            for e in a['events']:
                if e['stage']=='WIRE_START' and e['evidence'].get('chat_id')!= (config['chat_id'] if route['audience']=='group' else config.get('owner_private_chat_id')):
                    raise PermissionError('Original target changed')
        schedule=payload.get('scheduled_at',queued)
        stamp=datetime.fromtimestamp(schedule,timezone.utc).isoformat()
        prefix='补发｜原定 '+stamp+'；原因：已核验未发送，依赖已重新核验；关联事件 #'+str(ident)+'。'
        retry={**payload,'retry_of':ident,'reconciliation_review':review_id,'retry_explanation':prefix,'expires_at':expiry}
        cur=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,?,?,'PENDING')",
                      ('notification-retry:'+str(ident),item['kind'],encode(retry)))
        retry_id=cur.lastrowid
        c.execute('INSERT INTO notification_retry_authorizations VALUES(?,?,?,?,?)',(ident,review_id,evidence_fingerprint,now,retry_id))
    return retry_id


def notice(store,original_id,notice_kind,text):
    """At most one private notice per original/state; notices never supervise notices."""
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM notification_review_notices WHERE notification_id=? AND notice_kind=?',(original_id,notice_kind)).fetchone():return
        payload=dict(message_role='CONTROL',private_notice=True,reason=text,queued_at=store.clock(),original_notification_id=original_id)
        cur=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,'PENDING')",
                      ('notification-review:'+str(original_id)+':'+notice_kind,encode(payload)))
        c.execute('INSERT INTO notification_review_notices VALUES(?,?,?)',(original_id,notice_kind,cur.lastrowid))


def notice_batch(store,originals,notice_kind):
    """One concise private card per review pass; each original keeps a mapping."""
    if not originals:return
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        pending=[ident for ident in originals if not c.execute('SELECT 1 FROM notification_review_notices WHERE notification_id=? AND notice_kind=?',(ident,notice_kind)).fetchone()]
        if not pending:return
        text='投递核对｜事件 '+', '.join('#'+str(x) for x in pending)+'：'+('仍缺可靠结果证据，保留UNKNOWN/STARTED，不自动重放。' if notice_kind=='unresolved' else '已证实未发送，但补发条件未满足；详见逐次证据，未重发。')
        payload=dict(message_role='CONTROL',private_notice=True,reason=text,queued_at=store.clock(),original_notification_ids=pending)
        cur=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,'PENDING')",
                      ('notification-review-batch:'+notice_kind+':'+fingerprint(pending),encode(payload)))
        c.executemany('INSERT INTO notification_review_notices VALUES(?,?,?)',[(ident,notice_kind,cur.lastrowid) for ident in pending])


def activity_status(store,item):
    """Safe public companion for a private task/research result, no copied prose."""
    digest=(item['kind']=='RECOVERY' and item['payload'].get('recovery_digest_version')==1)
    if not digest and (item['kind']!='SECRETARY_REPLY' or item['payload'].get('message_role') not in ('TASK','RESEARCH','PROGRESS','INTELLIGENCE')):return
    if item['payload'].get('fixed_public_status') is True or item['payload'].get('private_notice') is True:return
    payload=dict(message_role='PROGRESS',fixed_public_status=True,queued_at=store.clock(),original_notification_id=item['id'])
    if digest:
        recovered=item['payload'].get('recovered_count');unresolved=item['payload'].get('unresolved_count')
        if any(type(v) is not int or not 0<=v<=1000 for v in (recovered,unresolved)):return
        payload['public_recovery_counts']={'recovered':recovered,'unresolved':unresolved}
    with closing(store.connect()) as c,c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,'PENDING')",
                  ('notification-public-status:'+str(item['id']),encode(payload)))


async def recover(store,coordinator,config,bot,report_root,*,limit=10):
    """One bounded pass by the existing notification owner after restart/recovery."""
    from .notification_center import get_item,recipient
    from .incident_telegram import verify_destination
    initialize(store)
    with closing(store.connect()) as c:
        cursor=c.execute("SELECT payload FROM incident_cursors WHERE source='notification-recovery-scan-v1'").fetchone()
        after=json.loads(cursor[0]) if cursor else 0
        rows=c.execute("""SELECT n.id FROM notification_outbox n WHERE n.status IN ('UNKNOWN','STARTED','NOT_SENT_EXHAUSTED')
          AND coalesce(json_extract(n.payload,'$.private_notice'),0)!=1
          AND (n.status!='NOT_SENT_EXHAUSTED' OR EXISTS(SELECT 1 FROM notification_attempts a WHERE a.notification_id=n.id))
          ORDER BY CASE WHEN n.id>? THEN 0 ELSE 1 END,n.id LIMIT ?""",(after,limit)).fetchall()
    decisions=[];unresolved=[];blocked=[]
    for ident, in rows:
        review=assess(store,ident);decisions.append(review['decision']);item=get_item(store,ident)
        if review['decision']=='ALREADY_ACCEPTED':
            # Receipt is proof; repair projections without invoking transport.
            with closing(store.connect()) as c,c:
                evidence,_=_evidence(c,ident)
                receipt=evidence['receipt']
                if not _receipt_valid(receipt):
                    receipt=next(e['evidence']['receipt'] for a in evidence['attempts'] for e in a['events'] if e['stage']=='ACCEPTED')
                    c.execute('INSERT OR IGNORE INTO notification_receipts VALUES(?,?)',(ident,encode(receipt)))
                c.execute("UPDATE notification_outbox SET status='TELEGRAM_ACCEPTED' WHERE id=?",(ident,))
                c.execute("UPDATE notification_delivery SET status='TELEGRAM_ACCEPTED',ack_received_at=coalesce(ack_received_at,?) WHERE notification_id=?",(store.clock(),ident))
            coordinator.finish_operation('notification:outbox:'+str(ident),'SENT_ACCEPTED')
        elif review['decision']=='PROVEN_UNSENT':
            try:
                async with __import__('asyncio').timeout(20):await verify_destination(bot,config,item)
                retry=authorize_retry(store,review['review_id'],review['evidence_fingerprint'],{**config,'_report_root':str(report_root)},dependency_verified=True)
                if retry:coordinator.finish_operation('notification:outbox:'+str(ident),'SAFE_TO_RETRY')
            except Exception as exc:
                blocked.append(ident)
        else:
            unresolved.append(ident)
    notice_batch(store,unresolved,'unresolved');notice_batch(store,blocked,'blocked')
    # Retry outcomes receive one private result notice, with its own outbox/ACK.
    with closing(store.connect()) as c:
        outcomes=c.execute("SELECT id,status,json_extract(payload,'$.retry_of') FROM notification_outbox WHERE json_extract(payload,'$.retry_of') IS NOT NULL AND status IN ('TELEGRAM_ACCEPTED','UNKNOWN','NOT_SENT_EXHAUSTED') ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    for ident,status,parent in outcomes:notice(store,parent,'retry_result','关联补发 #'+str(ident)+'（原事件 #'+str(parent)+'）：'+status+'。服务器确认不等于手机已读。')
    if rows:
        with closing(store.connect()) as c,c:
            c.execute("INSERT INTO incident_cursors VALUES('notification-recovery-scan-v1',?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload",(json.dumps(rows[-1][0]),))
    return {'reviewed':len(rows),'decisions':decisions,'grants_trading_permission':False}
