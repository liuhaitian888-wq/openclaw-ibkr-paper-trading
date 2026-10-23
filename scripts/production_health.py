"""Read-only production smoke/maintenance inspection; no trading or delivery."""
import argparse
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from trading.production_paths import (CODE_ROOT,PRODUCTION_WORKSPACE,STATE_ROOT,AUDIT_DB,
    FINANCIAL_LEDGER,DELIVERY_LEDGER,LOG_ROOT,REPORT_ROOT,maintenance_active)
from trading.production_guard import validate_workspace
from trading.production_diagnostics import command,context,process_inventory,process_snapshot,directory_size,read_json


def fresh(value, seconds=120):
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace('Z','+00:00'))).total_seconds()
        return 0 <= age <= seconds
    except (AttributeError,ValueError,TypeError):return False


def recent_resource(service):
    path=LOG_ROOT/(service+'-resources.log')
    try:
        with path.open('rb') as f:
            f.seek(max(0,path.stat().st_size-16384));lines=f.read().decode(errors='replace').splitlines()
        for line in reversed(lines):
            row=json.loads(line)
            if 'pid' in row:return row
    except (OSError,ValueError):pass
    return {}


def successful_delivery(ledger):
    records=ledger.get('reports',{})
    if not isinstance(records,dict):return None
    stamps=[r.get('finished_at') for r in records.values() if isinstance(r,dict)
            and r.get('status') in ('SENT_ACCEPTED','SENT_CONFIRMED') and not r.get('requires_review',True)
            and isinstance(r.get('finished_at'),str)]
    return max(stamps) if stamps else None


def smoke():
    checks={};details={}
    try:
        validate_workspace();checks['workspace']='OK'
    except RuntimeError as exc:checks['workspace']='FAIL';details['workspace']=str(exc)
    actual=context();manifest=read_json(STATE_ROOT/'production.json')
    checks['commit']='OK' if (manifest.get('ready') is True and manifest.get('commit')==actual['commit']
        and manifest.get('branch')==actual['branch'] and manifest.get('workspace')==str(CODE_ROOT)
        and manifest.get('state_root')==str(STATE_ROOT)
        and not command(['git','-C',str(CODE_ROOT),'status','--porcelain']).strip()) else 'FAIL'
    checks['state path']='OK' if STATE_ROOT.is_dir() and os.access(STATE_ROOT,os.R_OK|os.W_OK|os.X_OK) else 'FAIL'
    try:
        for name in ['api_service','scripts.run_autonomous_trading_agent','scripts.report_production_scheduler']:
            importlib.import_module(name)
        checks['imports']='OK'
    except Exception as exc:checks['imports']='FAIL';details['imports']=str(exc)
    processes=process_inventory();details['processes']=processes
    modes=[p for p in processes if 'run_autonomous_trading_agent.py' in p['command']]
    roles=['run_autonomous_trading_agent.py','api_service.py','report_production_scheduler.py','send_daily_visual_feishu_update.py']
    duplicates=any(sum(role in p['command'] for p in processes)>1 for role in roles) or any(p['legacy_worktree'] or p['deleted_cwd'] for p in processes)
    checks['single instance']='FAIL' if duplicates else 'OK'
    dbresults={}
    for path in [AUDIT_DB,FINANCIAL_LEDGER]:
        if not path.is_file():dbresults[str(path)]='MISSING';continue
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as c:
                c.execute('pragma query_only=on')
                # Smoke is bounded; full integrity reconciliation belongs to migration/worktree validation.
                c.execute('select name from sqlite_master limit 1').fetchall()
                dbresults[str(path)]='OK'
        except sqlite3.Error as exc:dbresults[str(path)]=str(exc)
    details['databases']=dbresults
    checks['database']='OK' if all(v=='OK' for v in dbresults.values()) and manifest.get('migration_verified') is True else 'FAIL'
    snapshots=[process_snapshot(p['pid']) for p in modes];details['resources']=snapshots
    resource_log=recent_resource('execution')
    checks['fd usage']='DEGRADED'
    if len(snapshots)==1 and resource_log.get('pid')==snapshots[0]['pid'] and fresh(resource_log.get('timestamp')):
        checks['fd usage']='OK' if resource_log.get('fd_status')=='OK' else 'FAIL'
    details['resource_history']=resource_log
    ibkr=read_json(REPORT_ROOT/'streaming_quote_diagnostics/latest.json')
    paper_port=int(os.environ.get('TWS_PORT','7497'))
    if paper_port not in (4002,7497):
        raise ValueError('Production health only supports Paper API ports 4002/7497')
    details['ibkr_listener_present']=bool(command(['lsof','-nP',f'-iTCP:{paper_port}','-sTCP:LISTEN','-t']).strip())
    checks['IBKR dependency']='OK' if (details['ibkr_listener_present'] and ibkr.get('connection_healthy') is True
        and fresh(ibkr.get('last_successful_ibkr_interaction'))) else 'DEGRADED'
    ledger=read_json(DELIVERY_LEDGER)
    # ACK freshness alone cannot prove all current network/auth dependencies.
    dependency=read_json(REPORT_ROOT/'dependency_health/latest.json').get('feishu',{})
    checks['Feishu dependency']='OK' if (ledger.get('schema_version')==2 and dependency.get('status')=='OK'
        and fresh(dependency.get('verified_at'))) else 'DEGRADED'
    details['delivery_schema_version']=ledger.get('schema_version')
    details['last_successful_Feishu_delivery']=successful_delivery(ledger)
    details['paused']=(STATE_ROOT/'PAUSED').exists();details['maintenance']=maintenance_active(STATE_ROOT)
    if details['paused'] or details['maintenance']:checks['execution gate']='FAIL'
    overall='READY' if all(v=='OK' for v in checks.values()) else 'NOT_READY'
    from reporting.health import resolve_modules
    observations={}
    try:
        recovery_path=STATE_ROOT/'runtime/recovery.sqlite3'
        with closing(sqlite3.connect(recovery_path.as_uri()+'?mode=ro',uri=True)) as c:
            observations={k:json.loads(v) for k,v in c.execute('SELECT name,payload FROM module_observations')}
    except (sqlite3.Error,ValueError):pass
    modules=resolve_modules(observations)
    from trading.production_guard import module_gate
    permissions={k:module_gate(k) for k in ('PRODUCTION_START_ALLOWED','ORDER_SUBMISSION_ALLOWED','FEISHU_SEND_ALLOWED')}
    if modules['SYSTEM']['state']!='HEALTHY' or not permissions['PRODUCTION_START_ALLOWED']['allowed']:overall='NOT_READY'
    return {'permissions':permissions,'checks':checks,'overall':overall,'module_overall':modules['SYSTEM']['state'],'modules':modules,'context':actual,'details':details}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');parser.add_argument('--maintenance',action='store_true')
    parser.add_argument('--refresh-adapters',action='store_true',help='Explicit bounded live readbacks and durable health observations; never starts services')
    parser.add_argument('--expected-account');parser.add_argument('--symbols',default='')
    args=parser.parse_args()
    if args.refresh_adapters:
        from reporting.recovery import RecoveryCoordinator,wire_live_adapters
        coordinator=RecoveryCoordinator(STATE_ROOT/'runtime/recovery.sqlite3')
        wire_live_adapters(coordinator,STATE_ROOT,PRODUCTION_WORKSPACE,expected_account=args.expected_account,
            symbols=tuple(x for x in args.symbols.split(',') if x))
        coordinator.tick()
    result=smoke()
    if args.maintenance:
        result['maintenance']={'state_directory_bytes':directory_size(STATE_ROOT),'log_directory_bytes':directory_size(LOG_ROOT),
            'watchdogs':command(['launchctl','print-disabled','gui/'+str(os.getuid())]),
            'last_successful_IBKR_interaction':read_json(REPORT_ROOT/'streaming_quote_diagnostics/latest.json').get('last_successful_ibkr_interaction','UNKNOWN'),
            'last_report_generation':read_json(REPORT_ROOT/'daily_trading/latest.json').get('timestamp','UNKNOWN'),
            'last_successful_Feishu_delivery':successful_delivery(read_json(DELIVERY_LEDGER)) or 'UNKNOWN'}
    if args.json:print(json.dumps(result,ensure_ascii=False,indent=2))
    else:
        for k,v in result['checks'].items():print(f'{k}: {v}')
        print('overall: '+result['overall'])
    return 0 if result['overall']=='READY' else 2

if __name__=='__main__':raise SystemExit(main())
