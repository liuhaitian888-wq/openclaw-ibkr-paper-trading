"""Persist operator attention independently of the one-shot restart ledger."""
import hashlib
import json
from contextlib import closing

from .gateway_recovery import ACCOUNT, ENDS, fresh

CAUSES = {'IDENTITY_UNVERIFIED', 'AUTHENTICATION_OPERATOR', 'BUSINESS_READINESS_UNVERIFIED', 'RECOVERY_UNVERIFIED'}
SOURCE = 'existing Gateway watchdog'
KIND = 'GATEWAY_OPERATOR_ATTENTION'


def _native_ready(native, now):
    return (native.get('connected') is True and native.get('identity') is True
            and native.get('upstream_connected') is True and native.get('dirty') is False
            and set(native.get('ends', [])) == ENDS
            and fresh(native.get('last_server_reply'), now, 10))


def observe(state, evidence, now):
    s = dict(state)
    e = evidence
    native = e.get('native', {})
    rb = e.get('readback', {})
    generation = e.get('generation')
    s.update(readiness_checked_at=now, readiness_requires_operator=False, readiness_phase='UNVERIFIED')
    episode = dict(s.get('readiness_episode', {}))
    healthy = (generation and _native_ready(native, now)
               and rb.get('complete') is True and rb.get('account_id') == ACCOUNT
               and rb.get('environment') == 'PAPER' and fresh(rb.get('at'), now, 420)
               and fresh(rb.get('server_time'),rb.get('at',0),30)
               and rb.get('at', 0) >= (e.get('generation_started_at') or 0) - 1)
    if episode.get('status') == 'OPEN':
        after = episode['opened_at']
        if (healthy and native['last_server_reply'] > after and rb['at'] > after
                and rb.get('server_time', 0) > after):
            if (s.get('readiness_healthy_generation') != generation
                    or not fresh(s.get('readiness_last_healthy'), now, 45)):
                s['readiness_healthy_since'] = now
            s.update(readiness_last_healthy=now, readiness_healthy_generation=generation)
            s['readiness_phase'] = 'VERIFYING_RECOVERY'
            if now - s['readiness_healthy_since'] >= 60:
                episode.update(status='RESOLVED', closed_at=now)
                s['readiness_phase'] = 'HEALTHY'
        else:
            s.pop('readiness_healthy_since', None)
            s.pop('readiness_last_healthy', None)
            in_progress = (s.get('operation') in ('STARTED', 'ACCEPTED')
                           and fresh(s.get('requested_at'), now, 600))
            s['readiness_phase'] = 'RECOVERY_IN_PROGRESS' if in_progress else 'OPERATOR_REQUIRED'
            s['readiness_requires_operator'] = not in_progress
        s['readiness_episode'] = episode
        return s

    # Attention never submits an operation, changes a restart budget or claims
    # the cause of a protocol handshake without business-ready callbacks.
    failure = (generation and e.get('service') == 'active'
               and rb.get('complete') is False and fresh(rb.get('at'), now, 420)
               and rb.get('gateway_api_handshake') is True and not _native_ready(native,now))
    hint = e.get('operator_observation') or {}
    auth = (hint.get('generation') == generation and hint.get('phase') in ('OPERATOR','CONFLICT')
            and fresh(hint.get('at'), now, 180))
    mismatch = (e.get('identity_mismatch') and fresh(rb.get('at'), now, 420)
                and rb.get('at', 0) >= (e.get('generation_started_at') or now) - 1)
    failed_recovery = s.get('operation') == 'OPERATOR_REQUIRED'
    explicit = generation and (auth or mismatch or failed_recovery) and not healthy
    if not failure and not explicit:
        s.pop('readiness_suspect', None)
        s['readiness_phase'] = 'HEALTHY' if healthy else 'UNVERIFIED'
        return s
    suspect = dict(s.get('readiness_suspect', {}))
    if suspect.get('generation') != generation or not fresh(suspect.get('last_poll'), now, 90):
        suspect = dict(generation=generation, since=now, failures=[])
    suspect['last_poll'] = now
    if failure:
        points = sorted(set(suspect['failures'] + [rb['at']]))
        suspect['failures'] = [points[0], points[-1]] if len(points) > 1 else points
    s['readiness_suspect'] = suspect
    s['readiness_phase'] = 'OBSERVING'
    sustained = (now - suspect['since'] >= 900 and len(suspect['failures']) == 2
                 and suspect['failures'][-1] - suspect['failures'][0] >= 60)
    if explicit or sustained:
        cause = ('IDENTITY_UNVERIFIED' if mismatch else 'RECOVERY_UNVERIFIED' if failed_recovery else
                 'AUTHENTICATION_OPERATOR' if auth else 'BUSINESS_READINESS_UNVERIFIED')
        identity = hashlib.sha256((str(generation) + ':' + str(now)).encode()).hexdigest()[:32]
        s['readiness_episode'] = dict(id=identity, generation=generation, opened_at=now,
                                      status='OPEN', cause=cause)
        s.pop('readiness_suspect', None)
        for field in ('readiness_healthy_since', 'readiness_last_healthy', 'readiness_healthy_generation'):
            s.pop(field, None)
        s.update(readiness_phase='OPERATOR_REQUIRED', readiness_requires_operator=True)
    return s


def publish(store, state):
    """Repeat immutable event ingestion after a crash; never repeat a send."""
    episode = state.get('readiness_episode')
    if not episode:
        return
    key = 'gateway-readiness:' + episode['id']
    opened = dict(
        severity='RED', scope='GATEWAY_READINESS', observed_at=episode['opened_at'],
        reason='Gateway业务连接未就绪，需要人工检查；原因以私聊中的新鲜证据为准，尚不能认定需要密码或手机验证。',
        cause=episode['cause'], requires_operator=True,
        action_taken='保留既有自动恢复政策及唯一服务；未新增登录、重启、券商请求或交易权限。',
        grants_trading_permission=False)
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        store._ingest(c, key + ':OPEN', 'gateway-readiness', json.dumps(opened,sort_keys=True),False,store.clock())
        # Auth phases already have one journal occurrence/private route. Do not
        # create a second private mirror from the watchdog observing that phase.
        if (episode['status'] == 'OPEN' and state.get('readiness_requires_operator') is True
                and episode['cause'] != 'AUTHENTICATION_OPERATOR'):
            payload=dict(scope='GATEWAY_READINESS',source=SOURCE,severity='RED',episode_id=episode['id'],cause=episode['cause'],
                         observed_at=episode['opened_at'],queued_at=episode['opened_at'],
                         requires_response=True,private_notice=True,grants_trading_permission=False)
            raw=json.dumps(payload,sort_keys=True)
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,?,?,'PENDING')",(key,KIND,raw))
            ident,original=c.execute('SELECT id,payload FROM notification_outbox WHERE incident_key=? AND kind=?',(key,KIND)).fetchone()
            if original!=raw:raise PermissionError('Immutable operator episode changed')
            registry=json.dumps(dict(notification_id=ident,kind=KIND,incident_key=key,generation=1,
                                     payload_sha256=hashlib.sha256(raw.encode()).hexdigest()),sort_keys=True)
            c.execute('INSERT OR IGNORE INTO incident_cursors VALUES(?,?)',('gateway-operator:'+episode['id'],registry))
            if c.execute('SELECT payload FROM incident_cursors WHERE source=?',('gateway-operator:'+episode['id'],)).fetchone()[0]!=registry:
                raise PermissionError('Operator notice registration changed')
        if episode['status'] == 'RESOLVED':
            payload=dict(
            severity='GREEN', scope='GATEWAY_READINESS', observed_at=episode['closed_at'],
            reason='Gateway新鲜完整Paper回读与独立回读已持续核验至少60秒；行情和交易门禁分别核验。',
            grants_trading_permission=False)
            store._ingest(c,key+':RESOLVED','gateway-readiness',json.dumps(payload,sort_keys=True),True,store.clock())


def operator_text(payload):
    if payload.get('cause') not in CAUSES:raise PermissionError('Known Gateway attention cause required')
    reason = {'BUSINESS_READINESS_UNVERIFIED':'协议仍可握手，但完整账户业务持续未就绪。',
              'IDENTITY_UNVERIFIED':'Paper身份核验未通过。',
              'RECOVERY_UNVERIFIED':'既有一次恢复后，完整回读仍未核验。',
              'AUTHENTICATION_OPERATOR':'检测到原生登录或会话阻塞。'}[payload['cause']]
    return 'Gateway需要人工检查\n'+reason+'\n请在本人IB官方客户端检查；若出现手机原生确认，请本人完成。不要在群聊发送密码或验证码。\n本提示没有新增登录或重启；交易门禁保持。'


def valid_operator_notice(store, item):
    """Host registration plus current durable condition, checked again pre-wire."""
    try:
        p=item['payload'];now=store.clock()
        if (item['kind']!=KIND or type(item.get('generation')) is not int or item['generation']!=1
                or type(item.get('id')) is not int or item['id']<=0
                or p.get('source')!=SOURCE or p.get('scope')!='GATEWAY_READINESS' or p.get('severity')!='RED'
                or p.get('cause') not in CAUSES or p.get('grants_trading_permission') is not False
                or p.get('requires_response') is not True or p.get('private_notice') is not True
                or not isinstance(p.get('episode_id'),str) or len(p['episode_id'])!=32
                or any(ch not in '0123456789abcdef' for ch in p['episode_id'])
                or item['incident_key']!='gateway-readiness:'+p['episode_id']):return False
        path=store.path.parent/'gateway-recovery-state.json'
        if path.is_symlink() or path.stat().st_size>1_000_000:return False
        with path.open() as f:state=json.load(f)
        ep=state.get('readiness_episode',{})
        if (ep.get('status')!='OPEN' or ep.get('id')!=p['episode_id'] or ep.get('cause')!=p['cause']
                or type(ep.get('opened_at')) not in (int,float) or not 0<=ep['opened_at']<=now
                or ep.get('opened_at')!=p.get('observed_at') or p.get('queued_at')!=ep.get('opened_at')
                or state.get('readiness_requires_operator') is not True
                or not fresh(state.get('readiness_checked_at'),now,90)):return False
        with closing(store.connect()) as c:
            row=c.execute('SELECT payload FROM incident_cursors WHERE source=?',('gateway-operator:'+p['episode_id'],)).fetchone()
            raw=c.execute('SELECT payload FROM notification_outbox WHERE id=?',(item['id'],)).fetchone()
            native=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        registry=json.loads(row[0]) if row else {}
        return bool(raw and json.loads(raw[0])==p and registry==dict(notification_id=item['id'],kind=KIND,
                    incident_key=item['incident_key'],generation=1,payload_sha256=hashlib.sha256(raw[0].encode()).hexdigest())
                    and native and (p['cause'] in ('IDENTITY_UNVERIFIED','RECOVERY_UNVERIFIED')
                                    or not _native_ready(json.loads(native[0]),now)))
    except (OSError,ValueError,TypeError,KeyError,AttributeError,__import__('sqlite3').Error):
        return False
