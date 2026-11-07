"""Bounded secretary RPC. SSH authenticates operator; Telegram authenticates owner."""
import asyncio
from contextlib import closing, redirect_stdout
import json
import logging
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize, accept_update, cursor, autonomous, claim, enqueue_reply, reconcile_replies, progress
from reporting.secretary_read import tool
from reporting.incident_telegram import verify_audience, verify_destination
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.secretary_controls import process_controls,tick_login,finish_start


async def poll(archive, root, config, armed_at):
    from telegram import Bot
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    async with asyncio.timeout(25):
        async with Bot(token=config['bot_token']) as bot:
            if config.get('audience_mode')=='shared_group':
                await verify_destination(bot,config,{'incident_key':'private-inbox-proof','kind':'SECRETARY_REPLY','payload':{}})
            else:
                await verify_audience(bot,config)
            if (await bot.get_webhook_info()).url:
                raise PermissionError('Existing webhook receiver; do not compete')
            updates=await bot.get_updates(offset=cursor(archive),limit=20,timeout=5,allowed_updates=['message'],read_timeout=10,connect_timeout=5)
            accepted=sum(accept_update(archive,json.loads(u.to_json()),config,armed_at=armed_at) for u in updates)
    return {'received':len(updates),'accepted':accepted}


def active_run(archive,run):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT instruction,state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()
    if row is None or row[1]!='STARTED':raise ValueError('Active reserved model run required')
    return row[0]


def dispatch(root,request,config,policy):
    archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive)
    action=request.get('action')
    if action=='poll':
        reconcile_replies(archive,IncidentStore(root/'runtime/recovery.sqlite3'))
        if policy.get('receiver_owner')=='cloud':
            from reporting.secretary_controls import pending_controls
            result={'controls':pending_controls(archive)}
        else:
            result=asyncio.run(poll(archive,root,config,policy['armed_at']))
            result['controls']=process_controls(archive,root,config,policy)
            tick_login(archive,root)
        if result['controls']:return result
        autonomous(archive,now=time.time())
        result['job']=claim(archive,model=policy['model'],now=time.time())
        if result['job']:progress(IncidentStore(root/'runtime/recovery.sqlite3'),result['job']['run'],'CLAIMED','已领取任务，等待受限模型分析；将记录数据来源与测试结果。')
        return result
    if action=='gateway_start_finished':return finish_start(archive,root,request)
    if action=='record_local_tool':
        instruction=active_run(archive,request['run']);step=request['step']
        if type(step) is not int or not 1<=step<=12 or request['request'].get('source')!='local_snapshot':raise ValueError('Bounded local snapshot evidence required')
        archive.append(request['run']+':tool:'+str(step),'der-secretary',origin='TOOL',kind='READ_ONLY_EXPERIMENT',parent=instruction,payload={'request':request['request'],'result':request['result'],'source':'verified local backup snapshot'})
        if step==1:progress(IncidentStore(root/'runtime/recovery.sqlite3'),request['run'],'FIRST_TOOL','已处理本机副本只读工具 '+str(request['request'].get('name'))+'；结果 '+str(request['result'].get('result',request['result'].get('state'))))
        return {'state':'ARCHIVED'}
    if action=='tool':
        instruction=active_run(archive,request['run']);step=request['step']
        if type(step) is not int or not 1<=step<=12:raise ValueError('Bounded tool step required')
        req=request['request']
        if req.get('source','cloud')!='cloud':raise ValueError('Cloud tool cannot impersonate local snapshot')
        try:
            if req.get('name') in ('engineering_proposal','engineering_updates'):
                from reporting.engineering_relay import propose,proposals
                result=propose(archive,req,instruction=instruction) if req['name']=='engineering_proposal' else proposals(archive)
            elif req.get('name')=='research_universe':
                if policy.get('agent_news_selection_approved') is not True:raise PermissionError('Agent news selection not approved')
                from reporting.research_universe import select
                result=select(archive,root,req,run=request['run'],instruction=instruction,step=step)
            else:result=tool(root,req)
        except (ValueError,PermissionError,KeyError,TypeError, __import__('sqlite3').Error) as exc:
            result={'state':'REFUSED_OR_UNAVAILABLE','error_type':type(exc).__name__,'message':str(exc)[:200]}
        archive.append(request['run']+':tool:'+str(step),'der-secretary',origin='TOOL',kind='READ_ONLY_EXPERIMENT',parent=instruction,payload={'request':req,'result':result})
        if step==1:progress(IncidentStore(root/'runtime/recovery.sqlite3'),request['run'],'FIRST_TOOL','已处理云端只读工具 '+str(req.get('name'))+'；结果 '+str(result.get('result',result.get('state'))))
        return result
    if action=='finish':
        run=request['run'];state=request['state']
        if state=='SUCCEEDED':
            # Repeated finish after an SSH ACK loss reconciles, never resends directly.
            with closing(archive.connect()) as c:
                row=c.execute('SELECT instruction FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()
            if row is None:raise ValueError('Reserved run required')
            result=request['result'];text=result['summary']
            if not isinstance(text,str) or not 0<len(text)<=3300:raise ValueError('Bounded public summary required')
            archive.append(run+':result','der-secretary',origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',parent=row[0],payload=result)
            archive.finish_run(run,state=state,result_event=run+':result')
            enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,text)
        elif state in ('FAILED','UNKNOWN'):
            archive.finish_run(run,state=state)
            IncidentStore(root/'runtime/recovery.sqlite3').ingest('secretary-risk:'+run,'secretary-risk:'+run,
                {'severity':'YELLOW','reason':'秘书模型运行结果待核对；已暂停新的自主研究，不自动重放计费调用。',
                 'scope':'SECRETARY','user_action':'需要核对模型额度、连接和本次运行结果；交易门禁保持。'})
        else:raise ValueError('Explicit terminal state required')
        return {'state':state,'run':run}
    if action=='status':return {'archive_events':len(archive.history('der-secretary',limit=500)),'databases':tool(root,{'name':'databases'})}
    raise PermissionError('Unknown RPC action')


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    raw=sys.stdin.read(60_001)
    if len(raw)>60_000:raise ValueError('Bounded request required')
    request=json.loads(raw)
    policy_path=root/'runtime/secretary-policy.json'
    policy=json.loads(policy_path.read_text())
    if (policy.get('approved') is not True or policy.get('grants_trading_permission') is not False
            or policy.get('model')!='gpt-6.1-sol' or type(policy.get('armed_at')) is not int):
        raise PermissionError('Approved read-only secretary policy required')
    config_path=Path.home()/'.config/openclaw/telegram.json'
    if config_path.stat().st_mode&0o077:raise PermissionError('Private Telegram configuration required')
    config=json.loads(config_path.read_text())
    with redirect_stdout(sys.stderr):
        with monitoring_service('secretary-rpc',root):
            result=dispatch(root,request,config,policy)
            coordinator=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
            if (root/'runtime/RISK_CONTROLS_REQUIRED').exists():
                from reporting.telegram_gate import current
                controls=current(root)
                coordinator.observe('RISK_CONTROLS','HEALTHY',freshness='FRESH',enabled=True,reason='Numeric risk cap document parsed; no execution authority',revision=controls['revision'])
            coordinator.observe('SECRETARY_ARCHIVE','HEALTHY',freshness='FRESH',reason='Secretary transaction completed')
            if request.get('action')=='finish':
                succeeded=request.get('state')=='SUCCEEDED'
                coordinator.observe('SECRETARY_MODEL','HEALTHY' if succeeded else 'DEGRADED',freshness='FRESH' if succeeded else 'UNKNOWN',reason='Bounded inference acknowledged' if succeeded else 'Paid outcome requires reconciliation')
                coordinator.observe('SECRETARY','HEALTHY' if succeeded else 'DEGRADED',freshness='FRESH' if succeeded else 'UNKNOWN',enabled=True,reason='Read-only secretary; trading authority unchanged')
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'state':'RPC_REFUSED','error_type':type(exc).__name__,'message':str(exc)[:200]}));sys.exit(2)
