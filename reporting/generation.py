"""One implementation for manual, scheduler and recovery; local source only."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from .errors import normalize

ACCOUNT_MAX_AGE_SECONDS=180  # reporting policy only; not a Trading risk parameter

def validation(report,now):
    issues=[]
    try:
        reference=datetime.fromisoformat(report['generated_at'].replace('Z','+00:00'))
        if reference.tzinfo is None or reference>now:raise ValueError('invalid generation time')
    except (KeyError,TypeError,ValueError):
        reference=now;issues.append(normalize('REPORT-DATE-001',now=now))
    p=report.get('performance',{});a=report.get('account',{})
    required=('net_liquidation','total_cash_value','available_funds','buying_power')
    history=p.get('trend',[])
    expected=p.get('expected_trading_days',0)
    complete=(expected>0 and p.get('observed_pnl_days')==expected and len(history)==expected and all(t.get('daily_pnl') is not None and t.get('currency') for t in history) and len({t.get('currency') for t in history})==1)
    if not complete or not p.get('complete_daily_pnl') or not report.get('activity',{}).get('coverage_complete'):
        issues.append(normalize('REPORT-DATA-INCOMPLETE',now=now))
    for key in required:
        m=a.get(key,{})
        if m.get('value') is None or not (m.get('currency') or a.get('currency')):
            issues.append(normalize('REPORT-DATA-INCOMPLETE',raw={'field':key},now=now));continue
        try:
            ts=datetime.fromisoformat(m['as_of'].replace('Z','+00:00'))
            age=(reference-ts).total_seconds()
            if ts.tzinfo is None or not 0<=age<=ACCOUNT_MAX_AGE_SECONDS or m.get('status') not in ('FRESH','AVAILABLE'):raise ValueError('stale')
        except (KeyError,TypeError,ValueError):issues.append(normalize('DATA-STALE-001',raw={'field':key,'as_of':m.get('as_of'),'threshold_seconds':ACCOUNT_MAX_AGE_SECONDS},now=now))
    if report.get('online_conflict'):issues.append(normalize('DATA-CONFLICT-001',raw=report['online_conflict'],now=now))
    return {'ready':not issues,'issues':issues,'evaluated_at':now.isoformat(),'local_only':True}

def generate(root,kind,now,output,*,trigger='manual',collector=None,renderer=None,simulation=False):
    if trigger not in ('manual','scheduler','recovery'):raise ValueError('Unknown trigger adapter')
    if collector is None:
        from scripts.report_aggregation import collect_report
        collector=collect_report
    if renderer is None:
        from scripts.report_rendering import write_report
        renderer=write_report
    report=collector(Path(root),kind,now)
    if simulation:report={**report,'simulation':True}
    check=validation(report,now)
    # Incomplete reports can be inspected locally, but never silently approved to send.
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    artifact=Path(renderer(report,output))
    manifest={'report_id':f"{kind.lower()}:{report['trading_period']['start_date']}:{report['trading_period']['end_date_exclusive']}",
              'report_type':kind,'report_date':report['report_date'],'trading_session':report['trading_period'],
              'artifact_path':str(artifact.resolve()),'artifact_hash':hashlib.sha256(artifact.read_bytes()).hexdigest(),
              'source_json':str((output/'latest.json').resolve()),'source_hash':hashlib.sha256((output/'latest.json').read_bytes()).hexdigest(),
              'created_at':now.isoformat(),'trigger_source':trigger,'simulation':simulation or report.get('simulation',False),'validation':check}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest
