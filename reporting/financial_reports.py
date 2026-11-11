"""Build existing white-grid report artifacts from saved, exact Paper readback only."""
from datetime import timezone
import json
import hashlib
from pathlib import Path

from scripts.report_aggregation import collect_report, read_json, stamp, period_for
from scripts.report_rendering import render_html, RENDER_VERSION
from reporting.report_schedule import BJ, due_types, period_signature


def source_diagnostics(observation, expected_account, now):
    """Fixed, non-sensitive predicates for the exact observation being evaluated."""
    observed = stamp(observation.get('observed_at'))
    valid_now = now.tzinfo is not None and now.utcoffset() is not None
    age = (now-observed).total_seconds() if valid_now and observed is not None else None
    reasons = []
    if not valid_now:
        reasons.append('CURRENT_TIME_INVALID')
    if observed is None:
        reasons.append('SOURCE_TIME_INVALID')
    elif age is not None:
        if age < 0:
            reasons.append('SOURCE_IN_FUTURE')
        elif age > 600:
            reasons.append('SOURCE_STALE')
    for failed, code in (
        (observation.get('source') != 'REAL_IBKR', 'SOURCE_NOT_REAL_IBKR'),
        (observation.get('complete') is not True, 'SOURCE_INCOMPLETE'),
        (observation.get('environment') != 'PAPER', 'ENVIRONMENT_MISMATCH'),
        (observation.get('account_id') != expected_account, 'ACCOUNT_MISMATCH'),
    ):
        if failed:
            reasons.append(code)
    canonical = json.dumps(observation, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return dict(reason_codes=reasons, source_snapshot_at=observed.isoformat() if observed else None,
                age_seconds=age, snapshot_sha256=hashlib.sha256(canonical.encode()).hexdigest())


def prepare_reports(root, expected_account, now, *, publish_image=None, transport="feishu"):
    if transport not in ("feishu", "smtp", "telegram"):
        raise ValueError("Unsupported report transport")
    root = Path(root)
    observation = read_json(root/'runtime/paper-observer.latest.json')
    observed = stamp(observation.get('observed_at'))
    source_check = source_diagnostics(observation, expected_account, now)
    if source_check['reason_codes']:
        return {'status': 'SOURCE_UNVERIFIED', 'prepared': [], 'source_check': source_check}
    day = now.astimezone(BJ).date()
    periods = {kind: period_for(kind, now) for kind in due_types(day)}
    required_close = max(stamp(period['last_session_close_utc']) for period in periods.values())
    if observed < required_close:
        return {'status': 'SOURCE_UNVERIFIED', 'prepared': [],
                'source_check': {**source_check, 'reason_codes': ['SOURCE_BEFORE_SESSION_CLOSE'],
                                 'required_session_close_at': required_close.isoformat()}}
    directory = root/'reports/financial'/day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    prepared = []
    from reporting.paper_readiness import collect as readiness_snapshot
    readiness=readiness_snapshot(root)
    manifest=read_json(root/'production.json')
    cashbook=read_json(root/'runtime/currency-book.latest.json')
    for kind in due_types(day):
        previous = read_json(directory/(kind+'.json'))
        if (period_signature(previous.get('trading_period')) == period_signature(periods[kind])
                and previous.get('render_version') == RENDER_VERSION and previous.get('source_snapshot_at') == observed.isoformat()
                and ((transport == 'feishu' and str(previous.get('image_key','')).startswith('img_')) or
                     (transport in ('smtp','telegram') and previous.get('image_path') == str(directory/(kind+'.png'))
                      and (directory/(kind+'.png')).is_file()
                      and previous.get('image_sha256') == hashlib.sha256((directory/(kind+'.png')).read_bytes()).hexdigest()))):
            prepared.append(kind)
            continue
        report = collect_report(root, kind, now, account_id=expected_account)
        # Only the exact readback owns current account fields. Historical ledger metrics stay independent.
        for key in report['account']:
            if key == 'positions':
                report['account'][key] = {'value': sum(float(x.get('position',0))!=0 for x in observation.get('positions', [])), 'status':'AVAILABLE',
                                          'source':'saved Paper readback','as_of':observed.isoformat()}
                continue
            field = observation.get('account', {}).get(key, {})
            field_at = stamp(field.get('source_timestamp'))
            fresh = field_at is not None and 0 <= (now-field_at).total_seconds() <= 600
            report['account'][key] = {'value':field.get('value'), 'currency':field.get('currency'),
                                     'status': 'AVAILABLE' if fresh and field.get('value') is not None else 'MISSING',
                                     'source':field.get('source','saved Paper readback'),
                                     'as_of':field_at.isoformat() if field_at else None}
            if not fresh:
                report['account'][key]['value'] = None
        report.update(render_version=RENDER_VERSION,account_id=expected_account, environment='PAPER', source_validated=True,
                      source_snapshot_at=observed.isoformat())
        # Missing ownership/protection evidence must never be rendered as protected.
        report['risk']['protection'] = {'text':'保护覆盖需独立核验','status':'UNKNOWN',
                                        'as_of':None,'fresh':False}
        if manifest.get('ready') is False or (root/'PAUSED').exists() or (root/'runtime/MAINTENANCE').exists():
            report.update(runtime_state='SAFE_MONITOR_ONLY / PAUSED',paper_readiness=False)
        if readiness['broker_state_verified']:
            holdings=readiness['holdings'];protected=sum(x['protection']=='PROTECTED' for x in holdings)
            missing=[x['symbol'] for x in holdings if x['protection']!='PROTECTED']
            report['risk']['protection']={'text':str(protected)+'/'+str(len(holdings))+' 持仓已核验保护'+('；缺口：'+', '.join(missing) if missing else ''),
                'status':'PROTECTED' if not missing else 'PARTIAL','as_of':readiness['observed_at'],'fresh':True}
        if cashbook.get('source')=='BROKER_API' and cashbook.get('account')==expected_account:
            balances=[]
            for currency in ('EUR','USD'):
                raw=cashbook.get('currencies',{}).get(currency,{}).get('amount')
                try:amount=float(raw)
                except (ValueError,TypeError):continue
                if __import__('math').isfinite(amount):balances.append(currency+' '+format(amount,',.2f'))
            report['cash_balance_note']='币种现金（独立快照）：'+' / '.join(balances)+'；截至 '+str(cashbook.get('observed_at'))+'。不代表下单时现金已核验。'
        html_path=directory/(kind+'.html')
        html_path.write_text(render_html(report))
        if publish_image is not None:
            published = publish_image(html_path, directory/(kind+'.png'))
            if published is None:
                png = directory/(kind+'.png')
                content = png.read_bytes()
                if not content.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('Rendered PNG required')
                report.update(image_path=str(png), image_sha256=hashlib.sha256(content).hexdigest())
            else:
                report['image_key'] = published
        for suffix, content in [('json',json.dumps(report,ensure_ascii=False,indent=2))]:
            path=directory/(kind+'.'+suffix)
            temporary=path.with_suffix(path.suffix+'.tmp')
            temporary.write_text(content)
            temporary.replace(path)
        prepared.append(kind)
    return {'status':'PREPARED','prepared':prepared,'directory':str(directory)}
