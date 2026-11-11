"""Single-sender automatic status projection; never owns broker permissions.

Raw occurrences remain in the private ledger. Only proven zero-wire pending
rows may be replaced by a current grouped view; uncertain sends never replay.
"""
from contextlib import closing
import hashlib
import json
import math
from contextlib import nullcontext

POLICY = 'grouped-v1'
COALESCE_SECONDS = 2
STABLE_SECONDS = 60
REMINDER_SECONDS = 900
HEALTH_POLL_GAP = 5
LIMIT = 500


def enabled(config):
    return (config.get('automatic_updates_to_group') is True
            and config.get('automatic_notification_policy') == POLICY)


def interactive(item):
    p = item['payload']
    if item['kind'] != 'SECRETARY_REPLY':
        return False  # An automatic fault requesting action is still a group status.
    if p.get('private_notice') is True:
        return False  # Supervisor/retry notices are automatic, despite CONTROL.
    if type(p.get('native_owner_reply')) is bool:
        return p['native_owner_reply']  # Host archive provenance, not model role.
    return (p.get('requires_response') is True or p.get('phase') == 'OPERATOR'
            or item['kind'] == 'SECRETARY_REPLY'
            and p.get('message_role') in ('ACK', 'CHAT', 'CONTROL', 'AUTH'))


def family(key):
    if key.startswith('paper-safety:'):
        return 'broker'
    return 'operations'


def batch_family(item):
    if interactive(item) or item['kind'] in ('AUTOMATIC_STATUS', 'CURRENT_RISK_STATUS'):
        return None
    p = item['payload']; kind = item['kind']
    if p.get('test_only') in (True,1) or p.get('scope')=='NOTIFICATION_CHANNEL_TEST':
        return 'test'
    if p.get('retry_of') is not None:
        return None  # Exact, separately reconciled attempts retain their identity.
    if p.get('private_notice') is True:
        return 'delivery'
    if kind=='SECRETARY_REPLY':
        from .notification_center import public_filing
        if public_filing(item) is None:
            return 'activity'
    if kind.startswith('AUTH_') or p.get('scope') == 'GATEWAY_AUTHENTICATION':
        return 'authentication'
    if (kind in ('ALERT', 'RECOVERY', 'CURRENT_SUMMARY')
            or kind.startswith(('ESCALATION_', 'PROTECTION_', 'REMINDER_'))):
        return family(item['incident_key'])
    return None


def initialize(store):
    with closing(store.connect()) as c, c:
        c.execute('''CREATE TABLE IF NOT EXISTS automatic_notification_sources (
          notification_id INTEGER PRIMARY KEY, family TEXT NOT NULL,
          disposition TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
          recorded_at REAL NOT NULL, aggregate_id INTEGER)''')
        c.execute('CREATE INDEX IF NOT EXISTS automatic_source_group ON automatic_notification_sources(family,aggregate_id,disposition)')
        c.execute('''CREATE TABLE IF NOT EXISTS automatic_notification_versions (
          notification_id INTEGER PRIMARY KEY,incident_key TEXT NOT NULL,
          generation INTEGER NOT NULL,payload_sha256 TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS automatic_projection_events (
          id INTEGER PRIMARY KEY,notification_id INTEGER NOT NULL,recorded_at REAL NOT NULL,
          reason TEXT NOT NULL,source_ids TEXT NOT NULL)''')


def _safe_unsent(c, ident):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_attempts'").fetchone():
        if c.execute('SELECT 1 FROM operation_attempts WHERE identity=?', ('notification:outbox:'+str(ident),)).fetchone():
            return False
    return (not c.execute('SELECT 1 FROM notification_delivery WHERE notification_id=?', (ident,)).fetchone()
            and not c.execute('SELECT 1 FROM notification_receipts WHERE notification_id=?', (ident,)).fetchone()
            and not c.execute('''SELECT 1 FROM notification_attempts a JOIN notification_attempt_events e
              ON e.attempt_id=a.id WHERE a.notification_id=? AND e.stage IN
              ('WIRE_START','ACCEPTED','UNKNOWN','REJECTED')''', (ident,)).fetchone())


def _put(c, key, value):
    c.execute('INSERT INTO incident_cursors VALUES (?,?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload',
              (key, json.dumps(value, sort_keys=True)))


def _open_snapshot(c, group):
    if group not in ('broker', 'operations'):
        return []
    rows = c.execute('''SELECT i.incident_key,i.generation,n.payload FROM incidents i
      LEFT JOIN notification_outbox n ON n.id=(SELECT max(x.id) FROM notification_outbox x
        WHERE x.incident_key=i.incident_key AND x.generation=i.generation)
      WHERE i.state='OPEN' AND coalesce(json_extract(n.payload,'$.test_only'),0)!=1
        AND coalesce(json_extract(n.payload,'$.scope'),'')!='NOTIFICATION_CHANNEL_TEST'
      ORDER BY i.incident_key LIMIT 1001''').fetchall()
    if len(rows) > 1000:
        raise RuntimeError('Automatic status inventory exceeds bounded scope')
    result = []
    for key, generation, raw in rows:
        if family(key) != group:
            continue
        p = json.loads(raw) if raw else {}
        rank = (3 if p.get('protection_status') in ('UNPROTECTED', 'PARTIALLY_PROTECTED')
                else 2 if p.get('severity')=='RED' else 1)
        result.append([key, generation, rank])
    return result


def _signature(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def _fault_watermark(c, group):
    if group not in ('broker','operations'):
        return 0
    predicate="incident_key LIKE 'paper-safety:%'" if group=='broker' else "incident_key NOT LIKE 'paper-safety:%'"
    return c.execute(f"""SELECT coalesce(max(id),0) FROM notification_outbox WHERE {predicate}
      AND coalesce(json_extract(payload,'$.test_only'),0)!=1
      AND coalesce(json_extract(payload,'$.scope'),'')!='NOTIFICATION_CHANNEL_TEST'
      AND (kind='ALERT' OR kind LIKE 'ESCALATION_%' OR kind LIKE 'PROTECTION_%')""").fetchone()[0]


def _paper_epoch(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_safety_state'").fetchone():
        return None
    row=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
    epoch=json.loads(row[0]).get('epoch') if row else None
    return epoch if isinstance(epoch,str) and 0<len(epoch)<=200 else None


def _track_health(store,c,state,group,snapshot,watermark,now,may_recover=False):
    new_fault=watermark!=state.get('fault_watermark',watermark)
    state['fault_watermark']=watermark
    if group!='broker':
        if new_fault:state['since']=now
        return
    epoch=_paper_epoch(c)
    clear=persistence_clear(store,c)
    reset=(bool(snapshot) and not may_recover or new_fault or not clear or not epoch
           or epoch!=state.get('healthy_epoch')
           or now-state.get('last_healthy_poll',float('-inf'))>HEALTH_POLL_GAP
           or now<state.get('last_healthy_poll',now))
    if reset:
        state.pop('healthy_since',None)
    if (not snapshot or may_recover) and clear and epoch and _fresh_paper(store,c,now):
        if 'healthy_since' not in state:state['healthy_since']=now
        state.update(last_healthy_poll=now,healthy_epoch=epoch)


def _recovery_facts(c,sources,context=()):
    candidates={tuple(x) for x in context}
    for ident,kind,raw in sources:
        if kind!='RECOVERY':continue
        p=json.loads(raw)
        ids=[ident]+[m.get('notification_id') for m in p.get('recovery_members',[]) if isinstance(m,dict)]
        for source in ids:
            row=c.execute("SELECT incident_key,generation,kind FROM notification_outbox WHERE id=?",(source,)).fetchone()
            if row and row[2]=='RECOVERY':candidates.add((row[0],row[1],source))
    facts={}
    for key,generation,ident in candidates:
        current=c.execute('SELECT generation,state FROM incidents WHERE incident_key=?',(key,)).fetchone()
        if current==(generation,'RESOLVED'):facts[(key,generation)]=[key,generation,ident]
    return sorted(facts.values())


def persistence_clear(store, c):
    """Negative gate shared with the Paper owner; unavailable helper fails closed."""
    try:
        from .local_persistence import has_local_persistence_fault
        return not has_local_persistence_fault(store.path.parent.parent, connection=c)
    except (ImportError, OSError, ValueError):
        return False


def _fresh_paper(store, c, now):
    if not persistence_clear(store, c):
        return False
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_safety_state'").fetchone():
        return False
    row = c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
    if not row:
        return False
    s = json.loads(row[0])
    def fresh(key, age):
        value = s.get(key)
        return type(value) in (int, float) and math.isfinite(value) and 0 <= now-value <= age
    return (s.get('connected') is True and s.get('identity') is True
            and s.get('upstream_connected') is True and s.get('dirty') is False
            and set(s.get('ends', [])) == {'orders', 'completed_orders', 'executions', 'positions'}
            and fresh('last_server_reply', 10) and fresh('reconciled_at', 30))


def prepare(store, config):
    """Bounded projection before the existing sender claims; no HTTP or clients."""
    if not enabled(config):
        return 0
    now = store.clock(); created = 0
    if 0 <= now-getattr(store, '_automatic_prepared_at', float('-inf')) < 1:
        return 0
    if not getattr(store, '_automatic_initialized', False):
        initialize(store)
        store._automatic_initialized = True
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        installation = c.execute("SELECT payload FROM incident_cursors WHERE source='automatic-policy:grouped-v1'").fetchone()
        if installation:
            cutover = json.loads(installation[0])['cutover_id']
        else:
            cutover = c.execute('SELECT coalesce(max(id),0) FROM notification_outbox').fetchone()[0]
            _put(c, 'automatic-policy:grouped-v1', {'cutover_id':cutover, 'installed_at':now})
        rows = c.execute("""SELECT id,incident_key,kind,payload FROM notification_outbox WHERE status='PENDING'
          AND (kind IN ('ALERT','RECOVERY','CURRENT_SUMMARY') OR kind LIKE 'ESCALATION_%'
            OR kind LIKE 'PROTECTION_%' OR kind LIKE 'REMINDER_%' OR kind LIKE 'AUTH_%'
            OR kind='SECRETARY_REPLY'
            OR json_extract(payload,'$.test_only')=1 OR json_extract(payload,'$.scope')='NOTIFICATION_CHANNEL_TEST'
            OR json_extract(payload,'$.private_notice')=1 OR json_extract(payload,'$.scope')='GATEWAY_AUTHENTICATION')
          ORDER BY id LIMIT ?""", (LIMIT,)).fetchall()
        touched = set()
        for ident, key, kind, raw in rows:
            item = dict(id=ident, incident_key=key, kind=kind, payload=json.loads(raw))
            group = batch_family(item)
            if group is None and ident <= cutover and item['payload'].get('retry_of') is not None:
                # Retain a previously queued, proven zero-wire automatic retry;
                # never move an already-authorized private retry into the group.
                original={**item, 'payload':{k:v for k,v in item['payload'].items() if k!='retry_of'}}
                group=batch_family(original)
            if group is None or not _safe_unsent(c, ident):
                continue
            disposition = 'test_evidence_retained' if group=='test' else 'cutover_retained' if ident <= cutover else 'grouped'
            c.execute('INSERT INTO automatic_notification_sources VALUES (?,?,?,?,?,NULL)',
                      (ident, group, disposition, hashlib.sha256(raw.encode()).hexdigest(), now))
            c.execute("UPDATE notification_outbox SET status='SUPPRESSED' WHERE id=? AND status='PENDING'", (ident,))
            if disposition == 'grouped':
                touched.add(group)
        groups = {key.removeprefix('automatic-group:') for key, in c.execute("SELECT source FROM incident_cursors WHERE source LIKE 'automatic-group:%'")}
        for group in sorted(groups | touched):
            cursor = 'automatic-group:'+group
            row = c.execute('SELECT payload FROM incident_cursors WHERE source=?', (cursor,)).fetchone()
            state = json.loads(row[0]) if row else {'revision':0, 'since':now}
            snapshot = _open_snapshot(c, group); signature = _signature(snapshot)
            if signature != state.get('signature'):
                state.update(signature=signature, since=now)
            watermark=_fault_watermark(c,group)
            key = 'automatic-status:'+group
            last = c.execute('''SELECT n.status,n.payload,d.attempt_started_at FROM notification_outbox n
              JOIN notification_delivery d ON d.notification_id=n.id WHERE n.incident_key=? ORDER BY n.id DESC LIMIT 1''', (key,)).fetchone()
            prior=json.loads(last[1]) if last else None
            source_rows = c.execute('''SELECT n.id,n.kind,n.payload FROM automatic_notification_sources a
              JOIN notification_outbox n ON n.id=a.notification_id WHERE a.family=?
              AND a.disposition='grouped' AND a.aggregate_id IS NULL ORDER BY n.id LIMIT ?''', (group, LIMIT)).fetchall()
            pending = c.execute("SELECT id,payload FROM notification_outbox WHERE incident_key=? AND status='PENDING'", (key,)).fetchall()
            pending_recovery=[json.loads(raw) for _,raw in pending if json.loads(raw).get('phase')=='RECOVERED'
                and json.loads(raw).get('signature')==signature and json.loads(raw).get('fault_watermark')==watermark]
            context=(prior or {}).get('recovery_facts',[])+[fact for p in pending_recovery for fact in p.get('recovery_facts',[])]
            facts=_recovery_facts(c,source_rows,context) if group in ('broker','operations') else []
            new_facts=_recovery_facts(c,source_rows) if group in ('broker','operations') else []
            recovery_signature=_signature(facts)
            if state.get('recovery_signature')!=recovery_signature:
                state.update(recovery_signature=recovery_signature,since=now)
            retained_partial=bool(prior and prior.get('phase')=='RECOVERED' and prior.get('signature')==signature
                                  and prior.get('fault_watermark')==watermark)
            recovering=bool(new_facts or pending_recovery or retained_partial)
            _track_health(store,c,state,group,snapshot,watermark,now,may_recover=recovering)
            for ident, raw in pending:
                p = json.loads(raw)
                if (p.get('signature') != signature or p.get('fault_watermark')!=watermark
                        or now >= p['expires_at']
                        or p.get('phase')=='RECOVERED' and group=='broker' and (
                            p.get('healthy_since')!=state.get('healthy_since')
                            or p.get('broker_epoch')!=state.get('healthy_epoch')
                            or not _fresh_paper(store,c,now))):
                    if _safe_unsent(c, ident):
                        c.execute("UPDATE notification_outbox SET status='SUPPRESSED' WHERE id=?", (ident,))
                        c.execute('UPDATE automatic_notification_sources SET aggregate_id=NULL WHERE aggregate_id=?', (ident,))
                else:
                    _put(c, cursor, state)
                    break
            else:
                if last and last[0] not in ('TELEGRAM_ACCEPTED', 'SMTP_ACCEPTED', 'FEISHU_ACCEPTED'):
                    _put(c, cursor, state); continue
                phase = ('RECOVERED' if recovering or not snapshot else 'FAULT') if group in ('broker','operations') else 'UPDATE'
                serious = sorted(x[0] for x in snapshot if x[2] == 3)
                ranks={x[0]:x[2] for x in snapshot}
                escalated=[k for k,v in ranks.items() if prior and v>prior.get('severity_ranks',{}).get(k,0)]
                escalation = bool(escalated)
                if escalation:phase='FAULT'  # An urgent rise never waits for partial-recovery stability.
                due = now-state['since'] >= (STABLE_SECONDS if phase == 'RECOVERED' else COALESCE_SECONDS)
                if phase == 'RECOVERED' and group == 'broker':
                    due = (due and now-state.get('healthy_since',now)>=STABLE_SECONDS
                           and _fresh_paper(store, c, now))
                if prior:
                    if phase == 'RECOVERED' and prior['phase'] == 'RECOVERED':
                        changed=(signature!=prior['signature'] or recovery_signature!=_signature(prior.get('recovery_facts',[])))
                        due = due and (changed or bool(snapshot and source_rows and now-last[2]>=REMINDER_SECONDS))
                    elif phase == 'FAULT' and prior['phase'] == 'FAULT' and not escalation:
                        due = due and now-last[2] >= REMINDER_SECONDS
                    elif phase == 'UPDATE':
                        due = due and bool(source_rows) and now-last[2] >= REMINDER_SECONDS
                if not source_rows and (not prior or phase != 'FAULT' or prior['phase'] != 'FAULT'):
                    due = False
                if due:
                    state['revision'] += 1
                    version_sources=[r for r in source_rows if phase!='FAULT' or r[1]!='RECOVERY']
                    members = []
                    if phase == 'RECOVERED':
                        for ident, kind, raw in source_rows:
                            p = json.loads(raw)
                            members.append({'notification_id':ident})
                            if kind == 'RECOVERY':
                                members.extend(p.get('recovery_members') or [{'notification_id':ident}])
                        members=list({m['notification_id']:m for m in members}.values())
                        members=list({m['notification_id']:m for m in members+[{'notification_id':f[2]} for f in facts]}.values())
                    nonce=_signature([key,state['revision'],watermark,now,[r[0] for r in version_sources]])
                    payload = dict(automatic_policy=POLICY, family=group, phase=phase,
                        version_nonce=nonce,
                        signature=signature, open_count=len(snapshot), serious_keys=serious,
                        severity_ranks=ranks,escalated_count=len(escalated),
                        recovered_count=len(facts),recovery_facts=facts,
                        source_count=len(version_sources), source_notification_ids=[r[0] for r in version_sources],
                        stable_since=state['since'], queued_at=now, expires_at=now+120,
                        healthy_since=state.get('healthy_since'),broker_epoch=state.get('healthy_epoch'),
                        fault_watermark=watermark,
                        severity='RED' if snapshot else 'GREEN' if phase=='RECOVERED' else 'YELLOW',
                        grants_trading_permission=False, recovery_members=members)
                    raw_payload=json.dumps(payload,sort_keys=True,allow_nan=False)
                    cur = c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,?,'AUTOMATIC_STATUS',?,'PENDING')", (key,state['revision'],raw_payload))
                    c.execute('INSERT INTO automatic_notification_versions VALUES (?,?,?,?)',
                              (cur.lastrowid,key,state['revision'],hashlib.sha256(raw_payload.encode()).hexdigest()))
                    c.executemany('UPDATE automatic_notification_sources SET aggregate_id=? WHERE notification_id=?', [(cur.lastrowid,r[0]) for r in version_sources])
                    created += 1
                _put(c, cursor, state)
            # The operator's scope is separate from configuration and the old
            # one-shot CURRENT_RISK_STATUS budget. Never invent authorization.
            from .grouped_current import register_authorized_pending
            register_authorized_pending(store,c,group)
    store._automatic_prepared_at = now
    return created


def valid(store, item, now, *, connection=None):
    if item['kind'] != 'AUTOMATIC_STATUS':
        return True
    p = item['payload']
    if (type(item.get('id')) is not int or item['id']<=0
            or type(item.get('generation')) is not int or item['generation']<=0
            or item.get('incident_key')!='automatic-status:'+str(p.get('family'))):
        return False
    if (p.get('automatic_policy') != POLICY or p.get('family') not in ('broker','operations','delivery','authentication','activity')
            or p.get('phase') not in ('FAULT','RECOVERED','UPDATE')
            or p.get('grants_trading_permission') is not False
            or type(p.get('expires_at')) not in (int,float) or not math.isfinite(p['expires_at'])
            or now >= p['expires_at'] or type(p.get('open_count')) is not int or not 0 <= p['open_count'] <= 1000):
        return False
    if (type(p.get('source_count')) is not int or not 0<=p['source_count']<=LIMIT
            or type(p.get('recovered_count')) is not int or not 0<=p['recovered_count']<=1000
            or not isinstance(p.get('recovery_facts'),list) or len(p['recovery_facts'])!=p['recovered_count']
            or any(not isinstance(f,list) or len(f)!=3 or not isinstance(f[0],str) or len(f[0])>500
                   or type(f[1]) is not int or f[1]<=0 or type(f[2]) is not int or f[2]<=0 for f in p['recovery_facts'])
            or type(p.get('escalated_count')) is not int or not 0<=p['escalated_count']<=1000
            or not isinstance(p.get('version_nonce'),str) or len(p['version_nonce'])!=64
            or any(x not in '0123456789abcdef' for x in p['version_nonce'])
            or not isinstance(p.get('serious_keys'),list) or len(p['serious_keys'])>1000
            or any(not isinstance(k,str) or not 1<=len(k)<=500 for k in p['serious_keys'])
            or not isinstance(p.get('source_notification_ids'),list) or len(p['source_notification_ids'])!=p['source_count']
            or any(type(i) is not int or i<=0 for i in p['source_notification_ids'])
            or len(set(p['source_notification_ids']))!=p['source_count']
            or not isinstance(p.get('severity_ranks'),dict) or len(p['severity_ranks'])>1000
            or any(not isinstance(k,str) or not 1<=len(k)<=500 or type(v) is not int or v not in (1,2,3) for k,v in p['severity_ranks'].items())
            or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) or p[k]>now for k in ('queued_at','stable_since'))
            or (p['family'] in ('broker','operations'))!=(p['phase'] in ('FAULT','RECOVERED'))):
        return False
    try: raw_payload=json.dumps(p,sort_keys=True,allow_nan=False)
    except (ValueError,TypeError):return False
    with (nullcontext(connection) if connection is not None else closing(store.connect())) as c:
        row=c.execute('''SELECT n.incident_key,n.generation,n.kind,n.payload,v.incident_key,v.generation,v.payload_sha256
          FROM notification_outbox n JOIN automatic_notification_versions v ON v.notification_id=n.id WHERE n.id=?''',(item['id'],)).fetchone()
        if (row is None or row[:4]!=(item['incident_key'],item['generation'],'AUTOMATIC_STATUS',raw_payload)
                or row[4:]!=(item['incident_key'],item['generation'],hashlib.sha256(raw_payload.encode()).hexdigest())):
            return False
        if _signature(_open_snapshot(c, p['family'])) != p.get('signature'):
            return False
        if _fault_watermark(c,p['family'])!=p.get('fault_watermark'):
            return False
        if p['phase'] == 'RECOVERED':
            if _recovery_facts(c,[],p['recovery_facts'])!=p['recovery_facts']:return False
            if now-p['stable_since']<STABLE_SECONDS:return False
            if p['family']=='broker':
                row=c.execute('SELECT payload FROM incident_cursors WHERE source=?',('automatic-group:broker',)).fetchone()
                state=json.loads(row[0]) if row else {}
                return (type(p.get('healthy_since')) in (int,float)
                    and now-p['healthy_since']>=STABLE_SECONDS
                    and state.get('healthy_since')==p['healthy_since']
                    and 0<=now-state.get('last_healthy_poll',float('-inf'))<=HEALTH_POLL_GAP
                    and p.get('broker_epoch')==_paper_epoch(c)
                    and _fresh_paper(store,c,now))
    return True


def release_before_wire(store,item,reason):
    """Reproject only a positively cancelled, registered zero-wire version."""
    if item['kind']!='AUTOMATIC_STATUS':return
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('''SELECT n.status,n.payload,v.payload_sha256 FROM notification_outbox n
          JOIN automatic_notification_versions v ON v.notification_id=n.id WHERE n.id=?''',(item['id'],)).fetchone()
        last=c.execute('''SELECT e.stage,e.evidence FROM notification_attempts a JOIN notification_attempt_events e ON e.attempt_id=a.id
          WHERE a.notification_id=? ORDER BY e.id DESC LIMIT 1''',(item['id'],)).fetchone()
        if (not row or row[0]!='SUPPRESSED' or row[1]!=json.dumps(item['payload'],sort_keys=True,allow_nan=False)
                or hashlib.sha256(row[1].encode()).hexdigest()!=row[2] or not _safe_unsent(c,item['id'])
                or not last or last[0]!='SUPPRESSED' or json.loads(last[1]).get('transport_entered') is not False):
            return
        sources=[r[0] for r in c.execute('SELECT notification_id FROM automatic_notification_sources WHERE aggregate_id=?',(item['id'],))]
        if not sources:return
        c.execute('UPDATE automatic_notification_sources SET aggregate_id=NULL WHERE aggregate_id=?',(item['id'],))
        c.execute('INSERT INTO automatic_projection_events(notification_id,recorded_at,reason,source_ids) VALUES (?,?,?,?)',
                  (item['id'],store.clock(),reason,json.dumps(sources)))
        cursor='automatic-group:'+item['payload']['family']
        raw=c.execute('SELECT payload FROM incident_cursors WHERE source=?',(cursor,)).fetchone()
        if raw:
            state=json.loads(raw[0]);state.pop('healthy_since',None);state.pop('last_healthy_poll',None)
            state['since']=store.clock();_put(c,cursor,state)


def rendered(item, at):
    p = item['payload']; phase = p['phase']
    if (type(p.get('source_count')) is not int or not 0<=p['source_count']<=LIMIT
            or type(p.get('open_count')) is not int or not 0<=p['open_count']<=1000
            or type(p.get('recovered_count')) is not int or not 0<=p['recovered_count']<=1000
            or type(p.get('escalated_count')) is not int or not 0<=p['escalated_count']<=1000
            or not isinstance(p.get('serious_keys'),list) or len(p['serious_keys'])>1000):
        raise PermissionError('Bounded registered summary fields required')
    label = {'broker':'券商连接与保护监测', 'operations':'服务运行',
             'delivery':'消息投递核对', 'authentication':'认证状态','activity':'研究与任务进度'}[p['family']]
    if phase == 'FAULT':
        text = label+'｜故障汇总\n仍待核验/处理 '+str(p['open_count'])+' 项。'
        if p.get('serious_keys'):
            text += '\n其中 '+str(len(p['serious_keys']))+' 项检测到保护覆盖缺口。'
        elif p.get('escalated_count'):
            text += '\n检测到新的严重故障或风险升级，已及时更新。'
        if p['family'] == 'broker':
            text += '\n覆盖券商服务器连接及其影响的检查；证据不足不等于保护单已撤销。'
    elif phase == 'RECOVERED':
        if p['open_count']:
            text = label+'｜部分恢复汇总\n已恢复 '+str(p['recovered_count'])+' 项检查；仍待核验/处理 '+str(p['open_count'])+' 项。\n恢复部分已连续核验至少60秒，其余故障继续跟踪。'
        else:
            text = label+'｜恢复汇总\n已恢复 '+str(p['recovered_count'])+' 项检查；相关故障已关闭，恢复状态已持续至少60秒。'
    else:
        text = label+'｜合并更新\n本轮 '+str(p['source_count'])+' 项状态已归档，详细证据可按需查询。'
    return text+'\n同类状态更新此卡；交易权限不变。事件 #'+str(item['id'])
