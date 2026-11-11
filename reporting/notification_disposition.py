"""Operator-recorded retirement of three delivery dependencies, never a resend.

Original outcomes stay unknown. Only a bound, fresh current-state report can use
the disposition; ordinary alerts, old digests and arbitrary UNKNOWNs cannot.
"""
from contextlib import closing
import hashlib
import json
import math

LEGACY={1270:('paper-safety:protection:NIO',7),1271:('paper-safety:protection:PFE',171),1272:('paper-safety:protection:T',7)}
ACTION='ARCHIVE_UNKNOWN_NO_REPLAY_CURRENT_RISK'


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
def sha(text):return hashlib.sha256(text.encode()).hexdigest()


def initialize(store):
    with closing(store.connect()) as c,c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS notification_disposition_scopes(
          scope_id TEXT PRIMARY KEY,authorized_at REAL NOT NULL,cutoff_id INTEGER NOT NULL,
          authorization TEXT NOT NULL,authorization_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_dependency_dispositions(
          notification_id INTEGER PRIMARY KEY,scope_id TEXT NOT NULL,incident_key TEXT NOT NULL,
          generation INTEGER NOT NULL,kind TEXT NOT NULL,original_status TEXT NOT NULL,
          original_payload TEXT NOT NULL,payload_sha256 TEXT NOT NULL,evidence TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_disposition_events(
          id INTEGER PRIMARY KEY,scope_id TEXT NOT NULL,notification_id INTEGER NOT NULL,
          action TEXT NOT NULL,recorded_at REAL NOT NULL,evidence TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_current_status(
          scope_id TEXT NOT NULL,notification_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,
          state_sha256 TEXT NOT NULL,observed_at REAL NOT NULL,expires_at REAL NOT NULL);
        ''')
        keys={row[1]:row[5] for row in c.execute('PRAGMA table_info(notification_current_status)')}
        if keys.get('scope_id')!=0 or keys.get('notification_id')!=1:
            raise PermissionError('Current-version registry migration requires explicit review')
    from .grouped_current import initialize as initialize_grouped
    initialize_grouped(store)


def _persistence_clear(c):
    from pathlib import Path
    from types import SimpleNamespace
    from .automatic_notifications import persistence_clear
    row=next((r for r in c.execute('PRAGMA database_list') if r[1]=='main'),None)
    return bool(row and row[2] and persistence_clear(SimpleNamespace(path=Path(row[2])),c))


def legacy_evidence(c,ident):
    result={table:list(c.execute(sql,(ident,))) for table,sql in (
        ('delivery','SELECT * FROM notification_delivery WHERE notification_id=?'),
        ('receipt','SELECT * FROM notification_receipts WHERE notification_id=?'),
        ('attempts','SELECT id,envelope_sha256 FROM notification_attempts WHERE notification_id=?'))}
    result['operations']=list(c.execute('SELECT * FROM operation_attempts WHERE identity=?',('notification:outbox:'+str(ident),)))
    return encoded(result)


def archive_dependencies(store,scope_id,authorization,expected):
    """Trusted operator only. The model has no write tool for this operation."""
    if (not isinstance(scope_id,str) or not 1<=len(scope_id)<=150
            or authorization.get('action')!=ACTION or authorization.get('origin')!='USER'
            or not all(isinstance(authorization.get(k),str) and authorization[k] for k in ('source_thread','source_message','user_text','interpretation'))
            or set(expected)!=set(LEGACY)):
        raise PermissionError('Exact three-occurrence operator disposition and owner provenance required')
    initialize(store);auth=encoded(authorization)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT authorization FROM notification_disposition_scopes WHERE scope_id=?',(scope_id,)).fetchone()
        if old:
            hashes=dict(c.execute('SELECT notification_id,payload_sha256 FROM notification_dependency_dispositions WHERE scope_id=?',(scope_id,)))
            if old[0]!=auth or hashes!=expected or not scope_valid(c,scope_id):raise PermissionError('Disposition identity/evidence reused or changed')
            return scope_id
        originals=[]
        for ident,(key,generation) in LEGACY.items():
            row=c.execute('SELECT incident_key,generation,kind,status,payload FROM notification_outbox WHERE id=?',(ident,)).fetchone()
            if row is None or row[:4]!=(key,generation,'ALERT','STARTED') or sha(row[4])!=expected[ident]:
                raise PermissionError('Original occurrence/status/raw payload differs')
            evidence=legacy_evidence(c,ident)
            if any(json.loads(evidence).values()):raise PermissionError('New positive evidence requires reconciliation first')
            originals.append((ident,scope_id,*row,sha(row[4]),evidence))
        cutoff=c.execute('SELECT coalesce(max(id),0) FROM notification_outbox').fetchone()[0]
        c.execute('INSERT INTO notification_disposition_scopes VALUES(?,?,?,?,?)',(scope_id,store.clock(),cutoff,auth,sha(auth)))
        c.executemany('INSERT INTO notification_dependency_dispositions VALUES(?,?,?,?,?,?,?,?,?)',originals)
        # Keep obsolete, never-attempted aggregate history, rather than flushing it.
        rows=c.execute("""SELECT id,payload FROM notification_outbox n WHERE id<=? AND status='PENDING' AND kind='RECOVERY'
          AND incident_key LIKE 'paper-safety:protection-recovery-batch:%' AND json_extract(payload,'$.scope')='PAPER_SAFETY'
          AND json_extract(payload,'$.recovery_digest_version')=1
          AND NOT EXISTS(SELECT 1 FROM notification_attempts a WHERE a.notification_id=n.id)
          AND NOT EXISTS(SELECT 1 FROM notification_delivery d WHERE d.notification_id=n.id)
          AND NOT EXISTS(SELECT 1 FROM notification_receipts r WHERE r.notification_id=n.id)
          AND NOT EXISTS(SELECT 1 FROM operation_attempts o WHERE o.identity='notification:outbox:'||n.id)""",(cutoff,)).fetchall()
        for ident,payload in rows:
            c.execute("UPDATE notification_outbox SET status='SUPERSEDED' WHERE id=? AND status='PENDING'",(ident,))
            c.execute('INSERT INTO notification_disposition_events(scope_id,notification_id,action,recorded_at,evidence) VALUES(?,?,?,?,?)',
                      (scope_id,ident,'OBSOLETE_UNATTEMPTED_DIGEST_SUPERSEDED',store.clock(),encoded({'original_payload':payload,'not_a_delivery_receipt':True})))
    return scope_id


def scope_valid(c,scope_id):
    scope=c.execute('SELECT authorization,authorization_sha256 FROM notification_disposition_scopes WHERE scope_id=?',(scope_id,)).fetchone()
    if not scope or sha(scope[0])!=scope[1]:return False
    authorization=json.loads(scope[0])
    if authorization.get('action')!=ACTION or authorization.get('origin')!='USER':return False
    rows=c.execute('SELECT notification_id,incident_key,generation,kind,original_status,original_payload,evidence FROM notification_dependency_dispositions WHERE scope_id=?',(scope_id,)).fetchall()
    if {x[0] for x in rows}!=set(LEGACY):return False
    for ident,*original,evidence in rows:
        row=c.execute('SELECT incident_key,generation,kind,status,payload FROM notification_outbox WHERE id=?',(ident,)).fetchone()
        if row!=tuple(original) or legacy_evidence(c,ident)!=evidence:return False
    return True


def proof(state,now):
    from .paper_readiness import ENDS
    if (any(state.get(k) is not True for k in ('identity','connected','upstream_connected'))
            or state.get('dirty') is not False or set(state.get('ends',[]))!=ENDS
            or not isinstance(state.get('epoch'),str) or not state['epoch']
            or any(type(state.get(k)) not in (int,float) or not math.isfinite(state[k]) or not 0<=now-state[k]<=limit
                   for k,limit in (('last_server_reply',10),('reconciled_at',60)))):
        raise PermissionError('Fresh complete owned Paper readback required')
    return sha(encoded({k:state.get(k) for k in ('epoch','positions','orders','contracts')}))


def _refresh_evidence(c,scope_id,previous,*,prior_to=None):
    """Every retained version must prove that no transport was reserved/entered."""
    versions=c.execute('SELECT notification_id,payload,state_sha256 FROM notification_current_status WHERE scope_id=? AND (? IS NULL OR notification_id<?) ORDER BY notification_id',(scope_id,prior_to,prior_to)).fetchall()
    evidence=[]
    for ident,payload,state_sha in versions:
        row=c.execute('SELECT status,payload FROM notification_outbox WHERE id=?',(ident,)).fetchone()
        allowed=('PENDING','NOT_SENT_EXHAUSTED') if prior_to is None and ident==previous else ('SUPERSEDED',)
        if not row or row[0] not in allowed or row[1]!=payload or any(json.loads(legacy_evidence(c,ident))[k] for k in ('delivery','receipt','operations')):
            raise PermissionError('A current version may have entered transport or changed')
        attempts=c.execute('SELECT id,envelope_sha256 FROM notification_attempts WHERE notification_id=? ORDER BY id',(ident,)).fetchall()
        if not attempts:raise PermissionError('Positive terminal preflight evidence required')
        events=[]
        for aid,envelope in attempts:
            stages=c.execute('SELECT id,stage,evidence FROM notification_attempt_events WHERE attempt_id=? ORDER BY id',(aid,)).fetchall()
            if not stages or any(stage!='PREFLIGHT_FAILED' for _,stage,_ in stages):
                raise PermissionError('Every attempt must terminate before wire')
            for _,_,raw in stages:
                detail=json.loads(raw)
                if (detail.get('wire_started') is True or detail.get('transport_entered') is True
                        or not (detail.get('wire_started') is False or detail.get('transport_entered') is False)):
                    raise PermissionError('Positive zero-wire terminal evidence required')
            events.append({'attempt_id':aid,'envelope_sha256':envelope,'events':stages})
        evidence.append({'notification_id':ident,'payload':payload,'state_sha256':state_sha,'attempts':events})
    return evidence


def queue_current(store,scope_id,*,refresh_unsent_reason=None):
    """One real current-state report, not a replay or synthetic recovery event."""
    from .paper_readiness import inventory
    if refresh_unsent_reason is not None and (not isinstance(refresh_unsent_reason,str) or not 1<=len(refresh_unsent_reason)<=500):
        raise PermissionError('Explicit bounded operator refresh reason required')
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if not scope_valid(c,scope_id):raise PermissionError('Disposition no longer matches original evidence')
        versions=c.execute('SELECT notification_id FROM notification_current_status WHERE scope_id=? ORDER BY notification_id',(scope_id,)).fetchall()
        previous=versions[-1][0] if versions else None
        if previous is not None and refresh_unsent_reason is None:return previous
        refresh=_refresh_evidence(c,scope_id,previous) if previous is not None else None
        if previous is None and refresh_unsent_reason is not None:raise PermissionError('No previous current report to refresh')
        now=store.clock();raw=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        if not _persistence_clear(c):raise PermissionError('Local persistence fault prevents current recovery report')
        state=json.loads(raw[0]) if raw else {};state_sha=proof(state,now)
        if now-state['reconciled_at']>20:raise PermissionError('Wait for next naturally completed broker readback')
        rows=inventory(state,verified=True)
        for symbol in sorted({o.get('symbol') for o in state.get('orders',{}).values()
                if not o.get('completed') and o.get('status') not in ('Filled','Cancelled','ApiCancelled','Inactive')
                and not state.get('positions',{}).get(o.get('symbol'))}):
            if not isinstance(symbol,str) or not symbol:raise PermissionError('Native order symbol missing')
            rows.append({'symbol':symbol,'protection':'REVIEW_REQUIRED','reason':'ACTIVE_ORDER_WITHOUT_POSITION'})
        if len(rows)>100:raise PermissionError('Bounded actual holdings required')
        recovered=sum(x['protection']=='PROTECTED' for x in rows);unresolved=len(rows)-recovered
        payload=dict(scope='CURRENT_PAPER_PROTECTION',data_classification='public_status',current_risk_scope=scope_id,
            queued_at=now,source_observed_at=state['reconciled_at'],expires_at=now+30,broker_epoch=state['epoch'],
            recovered_count=recovered,unresolved_count=unresolved,archived_unknown_count=3,
            reason='本次新鲜完整回读的当前保护核验；旧三条结果未知已封存且未重发，不冒充旧恢复通知的回执。',
            grants_trading_permission=False)
        if previous is not None:
            c.execute("UPDATE notification_outbox SET status='SUPERSEDED' WHERE id=?",(previous,))
        cur=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,?,'CURRENT_RISK_STATUS',?,'PENDING')",('paper-safety:current-status:'+scope_id,len(versions)+1,encoded(payload)))
        ident=cur.lastrowid
        c.execute('INSERT INTO notification_current_status VALUES(?,?,?,?,?,?)',(scope_id,ident,encoded(payload),state_sha,now,now+30))
        c.execute('INSERT INTO notification_disposition_events(scope_id,notification_id,action,recorded_at,evidence) VALUES(?,?,?,?,?)',
            (scope_id,ident,'CURRENT_STATUS_FROM_FRESH_NATIVE_READBACK',now,encoded({'broker_epoch':state['epoch'],'state_sha256':state_sha,'holdings':rows,'historical_outcomes':'UNKNOWN_NOT_REPLAYED'})))
        if refresh is not None:
            c.execute('INSERT INTO notification_disposition_events(scope_id,notification_id,action,recorded_at,evidence) VALUES(?,?,?,?,?)',
                (scope_id,ident,'CURRENT_STATUS_ZERO_WIRE_REFRESH',now,encoded({'operator_reason':refresh_unsent_reason,'previous_versions':refresh,'not_a_retry_of_uncertain_transport':True})))
    return ident


def claim_allowed(c,item,*,store=None,now=None):
    if item['kind']=='AUTOMATIC_STATUS' and item['payload'].get('phase')=='RECOVERED':
        row=c.execute('SELECT 1 FROM notification_grouped_current WHERE notification_id=?',(item['id'],)).fetchone()
        if row:
            from .grouped_current import grouped_current_valid
            return bool(store is not None and now is not None and grouped_current_valid(store,c,item,now))
        return True
    if item['kind']!='CURRENT_RISK_STATUS':return True
    if not _persistence_clear(c):return False
    scope=item['payload'].get('current_risk_scope')
    row=c.execute('SELECT payload FROM notification_current_status WHERE scope_id=? AND notification_id=?',(scope,item['id'])).fetchone()
    if row is None or row[0]!=encoded(item['payload']) or not scope_valid(c,scope):return False
    if c.execute('SELECT max(notification_id) FROM notification_current_status WHERE scope_id=?',(scope,)).fetchone()[0]!=item['id']:return False
    try:prior=_refresh_evidence(c,scope,item['id'],prior_to=item['id'])
    except (PermissionError,ValueError,TypeError):return False
    if prior:
        audit=c.execute("SELECT evidence FROM notification_disposition_events WHERE scope_id=? AND notification_id=? AND action='CURRENT_STATUS_ZERO_WIRE_REFRESH'",(scope,item['id'])).fetchall()
        if len(audit)!=1:return False
        try:
            if encoded(json.loads(audit[0][0])['previous_versions'])!=encoded(prior):return False
        except (KeyError,ValueError,TypeError):return False
    # Other uncertain protection occurrences remain barriers, even after this scope.
    return not c.execute("""SELECT 1 FROM notification_outbox n WHERE n.status IN ('STARTED','UNKNOWN')
      AND n.id!=? AND n.incident_key LIKE 'paper-safety:protection:%'
      AND n.id NOT IN (SELECT notification_id FROM notification_dependency_dispositions WHERE scope_id=?) LIMIT 1""",(item['id'],scope)).fetchone()


def validate_before_wire(store,item,now):
    if item['kind']=='AUTOMATIC_STATUS' and item['payload'].get('family')=='broker' and item['payload'].get('phase')=='RECOVERED':
        from .grouped_current import grouped_current_valid
        with closing(store.connect()) as c:
            registered=c.execute('SELECT 1 FROM notification_grouped_current WHERE notification_id=?',(item['id'],)).fetchone()
            unresolved=c.execute('''SELECT 1 FROM json_each(?,'$.recovery_members') member
              JOIN notification_outbox source ON source.id=json_extract(member.value,'$.notification_id')
              JOIN notification_outbox earlier ON earlier.incident_key=source.incident_key AND earlier.id<source.id
              WHERE earlier.status NOT IN ('SMTP_ACCEPTED','FEISHU_ACCEPTED','TELEGRAM_ACCEPTED','SUPERSEDED','NOT_SENT_EXHAUSTED','SUPPRESSED') LIMIT 1''',(encoded(item['payload']),)).fetchone()
            if (registered or unresolved) and not grouped_current_valid(store,c,item,now):
                raise PermissionError('Grouped current authorization or causal evidence changed')
        return
    if item['kind']!='CURRENT_RISK_STATUS':return
    with closing(store.connect()) as c:
        if not _persistence_clear(c):raise PermissionError('Local persistence fault prevents current recovery report')
        if not claim_allowed(c,item):raise PermissionError('Current-status administrative proof changed')
        row=c.execute('SELECT state_sha256,observed_at,expires_at FROM notification_current_status WHERE notification_id=?',(item['id'],)).fetchone()
        state=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
        if not 0<=now-row[1]<=30 or now>=row[2] or proof(state,now)!=row[0]:
            raise PermissionError('Current protection snapshot changed or expired')


from .grouped_current import (GROUPED_ACTION,authorize_grouped_current,register_grouped_current,
                             eligible_grouped_current_ids,grouped_current_valid)
