"""Pure, persisted bounded Gateway recovery decisions. No subprocesses or broker API."""
ACCOUNT = 'DUQ503649'
ENDS = {'positions', 'orders', 'completed_orders', 'executions'}


def fresh(stamp, now, limit):
    return type(stamp) in (int, float) and 0 <= now-stamp <= limit


def decide(state, evidence, now):
    s = dict(state)
    e = evidence
    generation = e.get('generation')
    native = e.get('native', {})
    readback = e.get('readback', {})
    live_api = fresh(native.get('last_server_reply'), now, 10)
    native_ok = (live_api and native.get('connected') is True and native.get('identity') is True
                 and native.get('upstream_connected') is True and native.get('dirty') is False
                 and set(native.get('ends', [])) == ENDS)
    independent_ok = (readback.get('complete') is True and readback.get('account_id') == ACCOUNT
                      and readback.get('environment') == 'PAPER'
                      and fresh(readback.get('at'), now, 420))
    reason = 'OBSERVING'
    action = 'NONE'
    pending = s.get('operation') in ('STARTED', 'ACCEPTED', 'OPERATOR_REQUIRED')
    if pending:
        after = s['requested_at']
        if (generation and generation != s.get('requested_generation') and native_ok and independent_ok
                and native['last_server_reply'] > after and readback['at'] > after
                and readback.get('server_time', 0) > after):
            s.setdefault('verified_since', now)
            if now-s['verified_since'] >= 60:
                s['operation'] = 'RECOVERED'
                reason = 'RECOVERED_READBACK_VERIFIED'
            else:
                reason = 'VERIFYING_RECOVERY'
        else:
            s.pop('verified_since', None)
            if now-after >= 600:
                s['operation'] = 'OPERATOR_REQUIRED'
            reason = 'OPERATOR_REQUIRED' if s['operation'] == 'OPERATOR_REQUIRED' else 'WAITING_RECONCILIATION_NO_REPLAY'
    elif (e.get('hold') or not e.get('approved') or e.get('service') != 'active'
          or not generation or e.get('identity_mismatch') or e.get('auth_required')):
        s.pop('suspect_since', None);s['failed_readbacks'] = []
        reason = 'HELD_OR_DEPENDENCY_UNVERIFIED'
    elif live_api:
        s.pop('suspect_since', None);s['failed_readbacks'] = []
        reason = 'API_RESPONSIVE' if native_ok else 'UPSTREAM_OR_RECONCILIATION_WAIT'
    elif fresh(readback.get('at'), now, 420) and readback.get('gateway_api_handshake') is True:
        s.pop('suspect_since', None);s['failed_readbacks'] = []
        reason = 'LOCAL_API_RESPONSIVE_UPSTREAM_WAIT'
    elif not (fresh(readback.get('at'), now, 420) and readback.get('complete') is False
              and readback.get('gateway_api_handshake') is False):
        reason = 'INDEPENDENT_FAILURE_EVIDENCE_UNAVAILABLE'
    else:
        if s.get('observed_generation') != generation:
            s['observed_generation'] = generation;s['generation_since'] = now
            s.pop('suspect_since', None);s['failed_readbacks'] = []
        s.setdefault('suspect_since', now)
        failures = sorted(set(s.get('failed_readbacks', [])+[readback['at']]))[-2:]
        s['failed_readbacks'] = failures
        # No-market-data, closed exchanges or 1100 alone do not enter this branch.
        if (now-s['generation_since'] < 900 or now-s['suspect_since'] < 900 or len(failures) < 2
                or failures[-1]-failures[0] < 60):
            reason = 'WAITING_SUSTAINED_HANG_CONFIRMATION'
        elif now-s.get('last_attempt', -86400) < 86400:
            reason = 'DAILY_RESTART_BUDGET_EXHAUSTED'
        else:
            s.update(operation='STARTED', requested_at=now, last_attempt=now,
                     requested_generation=generation, request_id=generation+':'+str(int(now)))
            action = 'RESTART_RESERVED';reason = 'SUSTAINED_LOCAL_API_HANG'
    if generation and s.get('observed_generation') != generation and not pending:
        s['observed_generation'] = generation;s['generation_since'] = now
    s.update(reason=reason, observed_at=now)
    return s, action
