"""Durable 09:00 Shanghai report dispatch; consumes prepared reports, never broker APIs."""
from contextlib import closing
from datetime import datetime, time, timezone
import json
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo
from scripts.report_aggregation import period_for

BJ = ZoneInfo('Asia/Shanghai')
LABELS = {'DAILY': '日报', 'WEEKLY': '周报', 'MONTHLY': '月报'}


def due_types(day):
    return ['DAILY'] + (['WEEKLY'] if day.weekday() == 0 else []) + (['MONTHLY'] if day.day == 1 else [])


def source_artifact(report, directory, day, kind, expected_account, now):
    """Validate new source contracts; legacy evidence is explicitly unavailable."""
    if 'source_snapshot' not in report:
        if 'source_check' in report:
            raise ValueError('New source contract is incomplete')
        return None
    record = report['source_snapshot']
    path = Path(directory)/day.isoformat()/(kind+'.SOURCE.json')
    if (not isinstance(record, dict) or record.get('encoding') != 'canonical-json-v1'
            or path.is_symlink() or Path(record.get('path', '')).resolve() != path.resolve()):
        raise ValueError('Exact source sidecar required')
    with path.open('rb') as handle:
        data = handle.read(10*1024*1024+1)
    if not 0 < len(data) <= 10*1024*1024 or hashlib.sha256(data).hexdigest() != record.get('sha256'):
        raise ValueError('Source sidecar identity changed')
    observation = json.loads(data)
    if not isinstance(observation, dict):
        raise ValueError('Source observation required')
    from .financial_reports import source_diagnostics
    check = source_diagnostics(observation, expected_account, now)
    saved_check = report.get('source_check')
    if (not isinstance(saved_check, dict) or saved_check.get('reason_codes') != []
            or check['reason_codes'] or check['snapshot_sha256'] != record['sha256']
            or check['source_snapshot_at'] != report['source_snapshot_at']
            or saved_check.get('snapshot_sha256') != record['sha256']):
        raise ValueError('Source identity/time/validation mismatch')
    return dict(path=str(path), sha256=record['sha256'])


def period_signature(period):
    if not isinstance(period, dict):
        return None
    return tuple(period.get(key) for key in ('start_date', 'end_date_exclusive', 'timezone', 'sessions_complete', 'partial'))


def ready_reports(directory, day, expected_account, now, *, transport="feishu"):
    ready, missing = {}, {}
    for kind in due_types(day):
        path = Path(directory) / day.isoformat() / (kind + '.json')
        try:
            report = json.loads(path.read_text())
            generated = datetime.fromisoformat(report['generated_at'])
            source_at = datetime.fromisoformat(report['source_snapshot_at'])
            if (generated.tzinfo is None or generated > now or generated.astimezone(BJ).date() != day
                    or source_at.tzinfo is None or not 0 <= (now-source_at).total_seconds() <= 600
                    or report.get('report_date') != day.isoformat()
                    or report.get('report_type') != kind
                    or report.get('account_id') != expected_account
                    or report.get('environment') != 'PAPER'
                    or report.get('source_validated') is not True
                    or (transport == 'feishu' and not str(report.get('image_key','')).startswith('img_'))):
                raise ValueError('Report identity/date/source not verified')
            expected_period = period_for(kind, now)
            if period_signature(report.get('trading_period')) != period_signature(expected_period):
                missing[kind] = ('交易期间待更新至纽约 ' + expected_period['start_date'] + ' 至 '
                                 + expected_period['end_date_exclusive'] + '（结束日不含）；等待正确期间报告')
                continue
            if source_at < datetime.fromisoformat(expected_period['last_session_close_utc']):
                missing[kind] = '源快照尚未覆盖该交易期间纽约20:00完整会话；等待会话结束后的新鲜完整回读'
                continue
            if transport in ('smtp','telegram'):
                png = (Path(directory)/day.isoformat()/(kind+'.png')).resolve()
                content = png.read_bytes()
                if (Path(report.get('image_path', '')).resolve() != png or not content.startswith(b'\x89PNG\r\n\x1a\n')
                        or report.get('image_sha256') != hashlib.sha256(content).hexdigest()):
                    raise ValueError('Local PNG identity not verified')
            source_artifact(report, directory, day, kind, expected_account, now)
            ready[kind] = report
        except (OSError, ValueError, KeyError, TypeError):
            missing[kind] = '报告缺失、日期不符或来源/账户未验证'
    return ready, missing



def _archived_missing_initial(c, ident, payload):
    """A quiet local missing notice is not an uncertain or delivered report."""
    if (payload.get('scope') != 'FINANCIAL_REPORTS'
            or payload.get('delivery_transport') != 'telegram'
            or payload.get('included_reports') != [] or payload.get('png_artifacts') != []
            or payload.get('report_manifests', []) != [] or not payload.get('missing_reports')):
        return False
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_archive'").fetchone():
        return False
    from .publication_policy import digest
    row=c.execute('SELECT policy,reason,payload_sha256 FROM publication_archive WHERE notification_id=?',(ident,)).fetchone()
    if row != ('publication-v2','report_status_is_not_a_report',digest(payload)):
        return False
    from .automatic_notifications import _safe_unsent
    return _safe_unsent(c,ident)



def quiet_supplement_valid(store, item):
    """Recheck the exact local predecessor proof at claim and before wire."""
    proof=item['payload'].get('quiet_initial_archive')
    if item['kind'] != 'REPORT_SUPPLEMENT' or proof is None:
        return True
    if (not isinstance(proof,dict) or set(proof) != {'notification_id','payload_sha256'}
            or type(proof['notification_id']) is not int):
        return False
    with closing(store.connect()) as c:
        row=c.execute('SELECT incident_key,kind,status,payload FROM notification_outbox WHERE id=?',
                      (proof['notification_id'],)).fetchone()
        if not row or row[:3] != (item['incident_key'],'REPORT_BUNDLE','SUPPRESSED'):
            return False
        payload=json.loads(row[3])
        from .publication_policy import digest
        return digest(payload)==proof['payload_sha256'] and _archived_missing_initial(c,proof['notification_id'],payload)


def enqueue_reports(store, directory, expected_account, now, *, transport="feishu"):
    if transport not in ("feishu", "smtp", "telegram"):
        raise ValueError("Unsupported report transport")
    if now.tzinfo is None:
        raise ValueError('Timezone-aware time required')
    if not isinstance(expected_account, str) or not expected_account.startswith('DU'):
        raise ValueError('Exact Paper account required')
    local = now.astimezone(BJ)
    day = local.date()
    scheduled = datetime.combine(day, time(9), BJ)
    if now < scheduled:
        return 'BEFORE_SCHEDULE'
    ready, missing = ready_reports(directory, day, expected_account, now, transport=transport)
    key = 'financial-reports:' + day.isoformat()
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        initial = c.execute('SELECT payload,status,id FROM notification_outbox WHERE incident_key=? AND kind=?',
                            (key, 'REPORT_BUNDLE')).fetchone()
        kind = 'REPORT_BUNDLE'
        selected = ready
        locally_archived = False
        if initial:
            initial_payload = json.loads(initial[0])
            locally_archived = (initial[1] == 'SUPPRESSED' and transport == 'telegram'
                                and _archived_missing_initial(c, initial[2], initial_payload))
            if initial[1] not in ('SMTP_ACCEPTED', 'FEISHU_ACCEPTED', 'TELEGRAM_ACCEPTED') and not locally_archived:
                return 'BLOCKED_INITIAL_UNCONFIRMED'
            selected = {k: ready[k] for k in initial_payload['missing_reports'] if k in ready}
            if not selected or c.execute('SELECT 1 FROM notification_outbox WHERE incident_key=? AND kind=?',
                                         (key, 'REPORT_SUPPLEMENT')).fetchone():
                return 'NO_SUPPLEMENT'
            kind = 'REPORT_SUPPLEMENT'
        elif (now - scheduled).total_seconds() >= 60:
            # A missed scheduled dispatch is an alert, not a silent late original report.
            kind = 'REPORT_BUNDLE'
        lines = ['计划发送（Asia/Shanghai）：' + scheduled.isoformat(),
                 '本次排队（UTC）：' + now.astimezone(timezone.utc).isoformat(),
                 '相对计划延迟秒数：' + str(int((now-scheduled).total_seconds()))]
        if kind == 'REPORT_SUPPLEMENT':
            lines += ['当日一次补报；延迟秒数：' + str(int((now - scheduled).total_seconds()))]
        for report_kind, report in selected.items():
            lines += [LABELS[report_kind] + '｜报告日（Asia/Shanghai）：' + report['report_date'],
                      '交易期间（America/New_York）：' + report['trading_period']['start_date'] + ' 至 '
                      + report['trading_period']['end_date_exclusive'] + '（结束日不含）',
                      '数据截至：' + str(report.get('source_snapshot_at') or '未提供')]
            for field, label in [('net_liquidation','净资产'), ('total_cash_value','现金'), ('daily_pnl','当日盈亏')]:
                metric = report.get('account', {}).get(field, {})
                lines.append(label + '：' + str(metric.get('value') if metric.get('value') is not None else '缺失')
                             + ' ' + str(metric.get('currency') or '') + ' [' + str(metric.get('status','MISSING')) + ']')
            lines.append('历史完整性：' + ('完整' if report.get('performance',{}).get('complete_daily_pnl') else '不完整，收益不可据此推断'))
        if missing:
            lines += ['缺报告警：' + '；'.join(LABELS[k] + '：' + v for k,v in missing.items())]
        payload = dict(severity='YELLOW' if missing else 'GREEN', reason='\n'.join(lines),
                       scope='FINANCIAL_REPORTS', delivery_transport=transport, queued_at=now.timestamp(),
                       scheduled_at=scheduled.timestamp(), included_reports=list(selected),
                       missing_reports=list(missing), grants_trading_permission=False,
                       image_keys=[report['image_key'] for report in selected.values() if 'image_key' in report],
                       png_artifacts=[dict(path=r['image_path'], sha256=r['image_sha256']) for r in selected.values() if transport in ('smtp','telegram')],
                       report_artifacts=[str(Path(directory)/day.isoformat()/(k+'.html')) for k in selected])
        if transport=='telegram':
            from .notification_artifacts import freeze
            payload['png_artifacts']=[freeze(directory,r['image_path'],r['image_sha256']) for r in selected.values()]
            snapshots=[]
            for k,r in selected.items():
                source=Path(directory)/day.isoformat()/(k+'.json')
                data=source.read_bytes()
                if json.loads(data)!=r:raise ValueError('Report manifest changed before immutable snapshot')
                snapshots.append(freeze(directory,source,hashlib.sha256(data).hexdigest()))
            payload['report_manifests']=snapshots
            originals = [source_artifact(r, directory, day, k, expected_account, now) for k,r in selected.items()]
            payload['source_snapshots'] = [freeze(directory, x['path'], x['sha256']) for x in originals if x is not None]
            payload['source_provenance_missing'] = [k for k,r in selected.items() if 'source_snapshot' not in r]
        if locally_archived:
            from .publication_policy import digest
            payload['quiet_initial_archive']=dict(notification_id=initial[2],payload_sha256=digest(initial_payload))
        payload['data_classification']='private_account' if selected else 'public_status'
        if selected:
            payload['expires_at']=min(datetime.fromisoformat(r['source_snapshot_at']).timestamp()+600 for r in selected.values())
        c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) "
                  "VALUES (?,1,?,?,'PENDING')", (key,kind,json.dumps(payload,ensure_ascii=False)))
    return kind
