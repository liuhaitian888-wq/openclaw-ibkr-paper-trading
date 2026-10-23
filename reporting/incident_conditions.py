"""Evidence interpreters only. No risk permission, orders, network or writes."""
from datetime import datetime, timezone


def observation_age(value, now):
    try:
        observed = datetime.fromisoformat(value)
        if observed.tzinfo is None:
            return None
        return now - observed.timestamp()
    except (TypeError, ValueError):
        return None


def protection_conditions(report, expected_account, now):
    source = report.get('source')
    if source not in ('position_guard', 'position_protection'):
        raise ValueError('Unrecognized protection report')
    stamp = report['timestamp']
    age = observation_age(stamp, now)
    fresh = age is not None and 0 <= age <= 600
    if source == 'position_guard':
        identity_ok = report.get('account') == expected_account
        if not identity_ok or (fresh and report.get('protection_evidence_complete') is True):
            yield ('protection-report-identity:' + expected_account, dict(
                timestamp=stamp, source=source, severity='GREEN' if identity_ok else 'RED', scope='ACCOUNT',
                reason='Verified protection report identity' if identity_ok else 'Protection report account missing or mismatched',
                action_taken='notification_recorded_only_no_order_changes',
                recovery_condition='Fresh complete exact-account protection report',
                grants_trading_permission=False), identity_ok)
        if not identity_ok:
            return
    if source == 'position_protection' and report.get('mode') != 'PAPER':
        raise ValueError('Protection repair report is not explicitly Paper')
    records = report['symbols'] if source == 'position_guard' else report['records']
    if len(records) > 500:
        raise ValueError('Protection batch exceeds limit')
    seen = set()
    for row in records:
        symbol = row['symbol']
        if not isinstance(symbol, str) or not symbol or symbol in seen:
            raise ValueError('Protection symbol identity missing or duplicated')
        seen.add(symbol)
        flags = ('duplicate_stop_warning', 'missing_stop_warning', 'overprotected_warning', 'underprotected_warning')
        statuses = list(row.get('confirmation_statuses', {}).values()) + list(row.get('confirmation_open_order_states', {}).values())
        failed = any(value in ('Rejected', 'Inactive', 'Cancelled', 'ApiCancelled') for value in statuses)
        warning = any(row.get(flag) is True for flag in flags) if source == 'position_guard' else failed
        if source == 'position_protection' and row.get('state_stale') is False and row.get('submitted') is False:
            warning = warning or float(row.get('uncovered_qty', 0)) > 0
        # Existing legacy reports can raise a warning, but cannot prove recovery.
        resolved = (source == 'position_guard' and fresh
                    and report.get('account') == expected_account
                    and report.get('protection_evidence_complete') is True
                    and row.get('position_covered_by_stop') is True
                    and all(row.get(flag) is False for flag in flags))
        if warning or resolved:
            key = ('protection:' + expected_account + ':' + symbol if report.get('account') == expected_account
                   else 'protection-unverified:' + symbol)
            yield (key, dict(
                timestamp=stamp, source=source, symbol=symbol, order_type=row.get('order_type', 'STP'),
                severity='GREEN' if resolved else 'RED', scope='SYMBOL',
                reason='Verified protection coverage' if resolved else 'Protection warning requires broker reconciliation',
                confirmation_statuses=statuses,
                evidence_freshness='FRESH' if fresh else 'STALE_OR_UNKNOWN',
                action_taken='notification_recorded_only_no_order_changes',
                user_action='Review current broker exposure and protective orders; no automatic repair',
                recovery_condition='Fresh complete exact-account position/order evidence and explicit coverage',
                grants_trading_permission=False), resolved)


def runtime_conditions(host, paper, expected_account, now):
    """Current symptoms; missing/stale never equals recovery or MFA diagnosis."""
    result = {}
    for name, value in (('host', host), ('paper', paper)):
        age = observation_age(value.get('observed_at'), now)
        fresh = age is not None and 0 <= age <= 600
        result[name + ':evidence'] = (not fresh, 'Fresh evidence observed' if fresh else 'Evidence missing, stale or future-dated', 'YELLOW', 'MODULE')
        if not fresh:
            continue
        if name == 'host':
            for service, state in value.get('services', {}).items():
                if service not in ('ibkr-display', 'ibkr-vnc', 'ibkr-web-vnc', 'ibkr-gateway', 'ibkr-api', 'ibkr-strategy'):
                    continue
                details = value.get('service_details', {}).get(service, {})
                expected_stopped = (service in ('ibkr-api', 'ibkr-strategy') and state == 'inactive'
                                    and details.get('unit_file_state') in ('disabled', 'masked'))
                result['service:' + service] = (state != 'active' and not expected_stopped,
                    'Service state: ' + str(state) + (' (expected disabled)' if expected_stopped else ''), 'YELLOW', 'MODULE')
        else:
            mismatch = (value.get('account_id') is not None and value.get('account_id') != expected_account
                        or value.get('environment') not in (None, 'PAPER')
                        or value.get('failure_class') == 'IDENTITY_MISMATCH')
            verified = (not mismatch and value.get('complete') is True and value.get('environment') == 'PAPER'
                        and value.get('source') == 'REAL_IBKR' and value.get('account_id') == expected_account
                        and value.get('resources', {}).get('connected_after_close') is False)
            reason = ('Fresh complete exact Paper readback; trading permission unchanged' if verified else
                      'Paper identity mismatch; human reconciliation required' if mismatch else
                      'Authentication or connection unverified; inspect Gateway, human login/MFA if required')
            result['paper:readback'] = (not verified, reason, 'RED' if mismatch else 'YELLOW', 'ACCOUNT')
    return result
