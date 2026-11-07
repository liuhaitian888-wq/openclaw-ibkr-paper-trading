"""Finite official-source intake; existing notification owner sends all messages."""
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.incidents import IncidentStore
from reporting.intelligence import initialize,public_sources,ingest,AUTH,CONVERSATION,paper_state,held_symbols,market_observations
from reporting.recovery import RecoveryCoordinator


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    config_path=Path.home()/'.config/openclaw/intelligence.json'
    if config_path.stat().st_mode&0o077:raise PermissionError('Private intelligence config required')
    config=json.loads(config_path.read_text());policy=json.loads((root/'runtime/intelligence-policy.json').read_text())
    if policy.get('approved') is not True or policy.get('grants_trading_permission') is not False:raise PermissionError('Approved read-only intake policy required')
    with monitoring_service('intelligence-public',root):
        archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive)
        store=IncidentStore(root/'runtime/recovery.sqlite3');now=time.time()
        retry_path=root/'runtime/intelligence-retries.json'
        config['_retry_state']=json.loads(retry_path.read_text()) if retry_path.exists() else {}
        results=public_sources(root,config);now=time.time();new=0
        retry_temp=retry_path.with_suffix('.tmp');retry_temp.write_text(json.dumps(config['_retry_state']));retry_temp.replace(retry_path)
        baseline_path=root/'runtime/intelligence-market-baseline.json'
        previous=json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        state=paper_state(root);records,baseline=market_observations(state,previous,now=time.time())
        results.append({'source':'EXISTING_PAPER_QUOTES','state':'OBSERVED' if baseline else 'NO_FRESH_EXISTING_QUOTES','records':records})
        temp=baseline_path.with_suffix('.tmp');temp.write_text(json.dumps(baseline));temp.replace(baseline_path)
        for result in results:
            records=result.pop('records');result['record_count']=len(records)
            for record in records:new+=ingest(archive,store,record,now=time.time(),armed_at=policy['armed_at'])
        with closing(archive.connect()) as c:
            recent=[json.loads(v) for (v,) in c.execute("SELECT payload FROM secretary_events WHERE kind='INTELLIGENCE_RECORD' AND recorded_at>=? ORDER BY rowid DESC LIMIT 10",(now-3600,)).fetchall()]
        fresh=[r for r in recent if r.get('alert_eligible')]
        with closing(archive.connect()) as c:
            existing=c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',('intel-research:'+str(int(now//3600)),)).fetchone()
        if fresh and not existing:
            archive.append('intel-research:'+str(int(now//3600)),CONVERSATION,origin='SYSTEM',kind='AUTONOMOUS_INSTRUCTION',parent=AUTH,payload={'text':'对本小时新情报做交叉验证。列出事实、来源、发布时间、持仓相关性、价格/成交量证据缺口及可证伪解释。标题不证明EPS/指引和因果，不发起交易。仅报告已实际完成的验证。','evidence':fresh[:5],'strategy_version':'intelligence-evidence-v1','fee_assumptions':'Not a trading or net-return conclusion'})
        complete=bool(results) and all(r['state'] in ('RETRIEVED','OBSERVED') for r in results)
        status={'observed_at':datetime.now(timezone.utc).isoformat(),'sources':results,'new_records':new,
                'causality_verified':False,'paid_services_purchased':False,'state':'RETRIEVED' if complete else 'PARTIAL_OR_UNAVAILABLE',
                'portfolio_symbols':held_symbols(paper_state(root)),'portfolio_scope':'Only fresh verified existing Paper-owner state; absence is not confirmed flat',
                'coverage_gaps':['Reuters/Bloomberg/Benzinga/TheFly/StockTitan/Newsquawk APIs not verified','Similarweb installed in ChatGPT; cloud API not connected','No validated earnings consensus/calendar or EPS/guidance extraction','No verified Nasdaq-index or volume-anomaly feed']}
        path=root/'runtime/intelligence.latest.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(status,indent=2));tmp.replace(path)
        RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('INTELLIGENCE_PUBLIC','HEALTHY' if complete else 'DEGRADED',freshness='FRESH' if complete else 'UNKNOWN',enabled=True,reason='Official-source poll completed; per-source coverage remains explicit',sources=results)
        print(json.dumps(status));return 0  # Per-source unavailability is recorded, not an infinite service restart.


if __name__=='__main__':raise SystemExit(main())
