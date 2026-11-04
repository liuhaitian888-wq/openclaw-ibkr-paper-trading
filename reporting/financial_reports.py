"""Build existing white-grid report artifacts from saved, exact Paper readback only."""
from datetime import timezone
import json
import hashlib
from pathlib import Path

from scripts.report_aggregation import collect_report, read_json, stamp
from scripts.report_rendering import render_html
from reporting.report_schedule import BJ, due_types


def prepare_reports(root, expected_account, now, *, publish_image=None, transport="feishu"):
    if transport not in ("feishu", "smtp"):
        raise ValueError("Unsupported report transport")
    root = Path(root)
    observation = read_json(root/'runtime/paper-observer.latest.json')
    observed = stamp(observation.get('observed_at'))
    if (now.tzinfo is None or observed is None or not 0 <= (now-observed).total_seconds() <= 600
            or observation.get('source') != 'REAL_IBKR' or observation.get('complete') is not True
            or observation.get('environment') != 'PAPER' or observation.get('account_id') != expected_account):
        return {'status': 'SOURCE_UNVERIFIED', 'prepared': []}
    day = now.astimezone(BJ).date()
    directory = root/'reports/financial'/day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    prepared = []
    for kind in due_types(day):
        previous = read_json(directory/(kind+'.json'))
        if (previous.get('source_snapshot_at') == observed.isoformat()
                and ((transport == 'feishu' and str(previous.get('image_key','')).startswith('img_')) or
                     (transport == 'smtp' and previous.get('image_path') == str(directory/(kind+'.png'))
                      and (directory/(kind+'.png')).is_file()
                      and previous.get('image_sha256') == hashlib.sha256((directory/(kind+'.png')).read_bytes()).hexdigest()))):
            prepared.append(kind)
            continue
        report = collect_report(root, kind, now, account_id=expected_account)
        # Only the exact readback owns current account fields. Historical ledger metrics stay independent.
        for key in report['account']:
            if key == 'positions':
                report['account'][key] = {'value': len(observation.get('positions', [])), 'status':'AVAILABLE',
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
        report.update(account_id=expected_account, environment='PAPER', source_validated=True,
                      source_snapshot_at=observed.isoformat())
        # Missing ownership/protection evidence must never be rendered as protected.
        report['risk']['protection'] = {'text':'保护覆盖需独立核验','status':'UNKNOWN',
                                        'as_of':None,'fresh':False}
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
