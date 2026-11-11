"""Single bounded research maintenance worker; never connects to the broker."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting import broad_screening as screening
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator


def notify(store,key,text):
    with closing(store.connect()) as c,c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,'PENDING')",
                  (key,json.dumps({'reason':text[:3000],'message_role':'CONTROL','delivery_transport':'telegram'},ensure_ascii=False)))


def run(root,*,immediate=False):
    policy=json.loads((root/'runtime/screening-policy.json').read_text())
    if (policy.get('approved') is not True or policy.get('environment')!='PAPER'
            or policy.get('public_research_readonly') is not True or policy.get('grants_trading_permission') is not False):
        raise PermissionError('Explicit research-only policy required')
    from reporting.storage_policy import preflight
    storage=preflight(root,'PUBLIC_SCREENING')
    if not storage['allowed']:return dict(storage,grants_trading_permission=False)
    archive=SecretaryArchive(root/'agent_secretary.sqlite3');screening.initialize(archive);now=time.time()
    # This process owns the single kernel service lock. Any previous STARTED
    # run was interrupted; paid/non-idempotent work is never repeated here.
    with closing(archive.connect()) as c,c:
        c.execute("UPDATE screen_refresh_jobs SET state='UNKNOWN',finished=? WHERE state='STARTED'",(now,))
    if immediate:screening.enqueue(archive,origin='ENGINEERING_AUTHORIZED_CURRENT_REQUEST',now=now)
    screening.schedule(archive,now)
    local=datetime.fromtimestamp(now,ZoneInfo('America/New_York'))
    if local.weekday()<5 and ((local.hour==9 and 40<=local.minute<50) or (local.hour==15 and 45<=local.minute<55)):
        from trading.broker_screening import queue,CODES
        for code in CODES:
            try:queue(archive,code,identity='schedule:'+str(local.date())+':'+str(local.hour)+':'+code,now=now)
            except ValueError:pass # persisted rate budget is not expanded
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        job=c.execute("SELECT id,origin FROM screen_refresh_jobs WHERE state='QUEUED' ORDER BY queued LIMIT 1").fetchone()
        if job:c.execute("UPDATE screen_refresh_jobs SET state='STARTED',started=? WHERE id=? AND state='QUEUED'",(now,job[0]))
    if not job:
        with closing(archive.connect()) as c:
            latest=c.execute("SELECT max(finished) FROM broker_screen_requests WHERE state='SUCCEEDED'").fetchone()[0]
            published=c.execute("SELECT max(json_extract(payload,'$.published_at')) FROM screen_pool_projection").fetchone()[0]
        if latest and (not published or latest>published):return screening.rebuild(archive,root,now=now,run='broker-projection:'+str(latest))
        return {'state':'NOT_DUE','grants_trading_permission':False}
    # Keep account contact local, never in logs, manifests or Telegram.
    config=Path.home()/'.config/openclaw/intelligence.json'
    sec_email=None
    if config.is_file():
        if config.stat().st_mode&0o077:raise PermissionError('Private public-data configuration required')
        sec_email=json.loads(config.read_text()).get('sec_contact_email')
    try:
        result=screening.refresh(archive,root,job[0],sec_email=sec_email,now=now)
        state='SUCCEEDED'
    except Exception as exc:
        result={'state':'PIPELINE_FAILED','error_type':type(exc).__name__,'grants_trading_permission':False};state='FAILED'
    with closing(archive.connect()) as c,c:
        c.execute('UPDATE screen_refresh_jobs SET state=?,finished=?,result=? WHERE id=? AND state=\'STARTED\'',(state,time.time(),json.dumps(result),job[0]))
    healthy=state=='SUCCEEDED' and result.get('sources',{}).get('NASDAQ_SCREENER')=='AVAILABLE_RESEARCH'
    RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('BROAD_SCREENING','HEALTHY' if healthy else 'DEGRADED',freshness='FRESH',
        reason='Research source intake only; field coverage and permissions remain separate',enabled=True,result=result,grants_trading_permission=False)
    if job[1].startswith('TELEGRAM:'):
        notify(IncidentStore(root/'runtime/recovery.sqlite3'),'screen-refresh:'+job[0],
               '研究数据维护结果：'+state+'\n'+json.dumps(result,ensure_ascii=False)+'\n/screen 查看研究候选；/data_status 查看缺口。')
    return result


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    if sys.argv[1:] not in ([],['--initial']):raise ValueError('Fixed invocation required')
    with monitoring_service('broad-screening-maintenance',root):
        print(json.dumps(run(root,immediate=sys.argv[1:]==['--initial']),sort_keys=True))


if __name__=='__main__':main()
