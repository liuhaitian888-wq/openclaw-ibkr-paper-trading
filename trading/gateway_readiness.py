"""Persist operator attention independently of the one-shot restart ledger."""
import hashlib

from .gateway_recovery import ACCOUNT, ENDS, fresh


def observe(state, evidence, now):
    s = dict(state)
    e = evidence
    native = e.get('native', {})
    rb = e.get('readback', {})
    generation = e.get('generation')
    episode = dict(s.get('readiness_episode', {}))
    healthy = (generation and native.get('connected') is True
               and native.get('identity') is True and native.get('upstream_connected') is True
               and native.get('dirty') is False and set(native.get('ends', [])) == ENDS
               and fresh(native.get('last_server_reply'), now, 10)
               and rb.get('complete') is True and rb.get('account_id') == ACCOUNT
               and rb.get('environment') == 'PAPER' and fresh(rb.get('at'), now, 420))
    if episode.get('status') == 'OPEN':
        after = episode['opened_at']
        if (healthy and native['last_server_reply'] > after and rb['at'] > after
                and rb.get('server_time', 0) > after):
            if (s.get('readiness_healthy_generation') != generation
                    or not fresh(s.get('readiness_last_healthy'), now, 45)):
                s['readiness_healthy_since'] = now
            s.update(readiness_last_healthy=now, readiness_healthy_generation=generation)
            if now - s['readiness_healthy_since'] >= 60:
                episode.update(status='RESOLVED', closed_at=now)
        else:
            s.pop('readiness_healthy_since', None)
            s.pop('readiness_last_healthy', None)
        s['readiness_episode'] = episode
        return s

    # Attention never submits an operation, changes a restart budget or claims
    # the cause of a protocol handshake without business-ready callbacks.
    failure = (generation and e.get('service') == 'active'
               and rb.get('complete') is False and fresh(rb.get('at'), now, 420)
               and rb.get('gateway_api_handshake') is True and not healthy)
    explicit = generation and (e.get('auth_required') or e.get('identity_mismatch')) and not healthy
    if not failure and not explicit:
        s.pop('readiness_suspect', None)
        return s
    suspect = dict(s.get('readiness_suspect', {}))
    if suspect.get('generation') != generation or not fresh(suspect.get('last_poll'), now, 90):
        suspect = dict(generation=generation, since=now, failures=[])
    suspect['last_poll'] = now
    if failure:
        points = sorted(set(suspect['failures'] + [rb['at']]))
        suspect['failures'] = [points[0], points[-1]] if len(points) > 1 else points
    s['readiness_suspect'] = suspect
    sustained = (now - suspect['since'] >= 900 and len(suspect['failures']) == 2
                 and suspect['failures'][-1] - suspect['failures'][0] >= 60)
    if explicit or sustained:
        cause = ('IDENTITY_UNVERIFIED' if e.get('identity_mismatch') else
                 'AUTHENTICATION_OPERATOR' if explicit else 'BUSINESS_READINESS_UNVERIFIED')
        identity = hashlib.sha256((str(generation) + ':' + str(now)).encode()).hexdigest()[:32]
        s['readiness_episode'] = dict(id=identity, generation=generation, opened_at=now,
                                      status='OPEN', cause=cause)
        s.pop('readiness_suspect', None)
        for field in ('readiness_healthy_since', 'readiness_last_healthy', 'readiness_healthy_generation'):
            s.pop(field, None)
    return s


def publish(store, state):
    """Repeat immutable event ingestion after a crash; never repeat a send."""
    episode = state.get('readiness_episode')
    if not episode:
        return
    key = 'gateway-readiness:' + episode['id']
    store.ingest(key + ':OPEN', 'gateway-readiness', dict(
        severity='RED', scope='GATEWAY_READINESS', observed_at=episode['opened_at'],
        reason='Gateway业务连接未就绪，需要人工检查；原因以私聊中的新鲜证据为准，尚不能认定需要密码或手机验证。',
        cause=episode['cause'], requires_operator=True,
        action_taken='保留既有自动恢复政策及唯一服务；未新增登录、重启、券商请求或交易权限。',
        grants_trading_permission=False))
    if episode['status'] == 'RESOLVED':
        store.ingest(key + ':RESOLVED', 'gateway-readiness', dict(
            severity='GREEN', scope='GATEWAY_READINESS', observed_at=episode['closed_at'],
            reason='Gateway新鲜完整Paper回读与独立回读已持续核验至少60秒；行情和交易门禁分别核验。',
            grants_trading_permission=False), resolved=True)
