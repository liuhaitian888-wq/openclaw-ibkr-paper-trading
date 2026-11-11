"""Bounded secretary RPC. SSH authenticates operator; Telegram authenticates owner."""
import asyncio
from contextlib import closing, redirect_stdout, nullcontext
import json
import logging
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize, accept_update, cursor, autonomous, claim, enqueue_reply, reconcile_replies, progress, checkpoint, reconcile_acknowledgements
from reporting.secretary_read import tool
from reporting.secretary_conversation import response_mode
from reporting.incident_telegram import verify_audience, verify_owner_private
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.secretary_controls import process_controls,tick_login,finish_start


async def poll(archive, root, config, armed_at, *, owned_bot=None, proof=None):
    from telegram import Bot
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)
    async with asyncio.timeout(25):
        async with (nullcontext(owned_bot) if owned_bot is not None else Bot(token=config['bot_token'])) as bot:
            verify=proof is None or not 0<=time.monotonic()-proof.get('at',0)<30
            if verify and config.get('audience_mode')=='shared_group':
                await verify_owner_private(bot,config)
            elif verify:
                await verify_audience(bot,config)
            if verify and (await bot.get_webhook_info()).url:
                raise PermissionError('Existing webhook receiver; do not compete')
            if verify and proof is not None:proof['at']=time.monotonic()
            updates=await bot.get_updates(offset=cursor(archive),limit=20,timeout=5,allowed_updates=['message'],read_timeout=10,connect_timeout=5)
            accepted=sum(accept_update(archive,json.loads(u.to_json()),config,armed_at=armed_at) for u in updates)
            policy_path=root/'runtime/secretary-policy.json'
            model_owner=json.loads(policy_path.read_text()).get('model_owner','mac_bridge') if policy_path.exists() else 'mac_bridge'
            reconcile_acknowledgements(archive,IncidentStore(root/'runtime/recovery.sqlite3'),model_owner=model_owner)
    return {'received':len(updates),'accepted':accepted}


def active_run(archive,run):
    with closing(archive.connect()) as c:
        row=c.execute('SELECT instruction,state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()
    if row is None or row[1]!='STARTED':raise ValueError('Active reserved model run required')
    return row[0]


def dispatch(root,request,config,policy,*,caller='mac_bridge'):
    archive=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(archive)
    action=request.get('action')
    if action in ('model_started','model_finished'):
        instruction=active_run(archive,request['run']);turn=request['turn']
        if type(turn) is not int or not 1<=turn<=3:raise ValueError('Bounded model turn required')
        inserted=archive.append(request['run']+':'+action+':'+str(turn),'der-secretary',origin='SYSTEM',kind=action.upper(),parent=instruction,
            payload={'turn':turn,'duration_seconds':request.get('duration_seconds')})
        if action=='model_started' and not inserted:raise ValueError('Model occurrence already started; reconcile, never replay')
        return {'state':'ARCHIVED'}
    if action=='poll':
        reconcile_replies(archive,IncidentStore(root/'runtime/recovery.sqlite3'))
        if policy.get('receiver_owner')=='cloud':
            from reporting.secretary_controls import pending_controls
            if caller=='mac_bridge':
                kinds=('TELEGRAM_SEARCH_REQUESTED',) if policy.get('gateway_start_control_owner')=='cloud_inbox' else ('GATEWAY_START_REQUESTED','TELEGRAM_SEARCH_REQUESTED')
                result={'controls':pending_controls(archive,kinds=kinds,owner='mac_bridge')}
            else:result={'controls':[]}  # Cloud model never consumes device/transport controls it cannot execute.
        else:
            result=asyncio.run(poll(archive,root,config,policy['armed_at']))
            result['controls']=process_controls(archive,root,config,policy)
            tick_login(archive,root)
        if policy.get('model_owner','mac_bridge')!=caller:
            result['job']=None;return result
        if result['controls'] and caller not in ('cloud_api','cloud_oauth'):return result
        if (root/'runtime/SECRETARY_MODEL_DRAIN').exists():
            result['job']=None;return result
        autonomous(archive,now=time.time())
        result['job']=claim(archive,model=policy['model'],now=time.time(),resume_after=policy.get('model_owner_since',0) if caller in ('cloud_api','cloud_oauth') else 0)
        if result['job'] and result['job']['payload'].get('autonomous'):progress(IncidentStore(root/'runtime/recovery.sqlite3'),result['job']['run'],'CLAIMED','已领取任务，等待受限模型分析；将记录数据来源与测试结果。')
        return result
    if action=='task_description':
        instruction=active_run(archive,request['run'])
        with closing(archive.connect()) as c:
            row=c.execute('SELECT payload,kind FROM secretary_events WHERE occurrence=?',(instruction,)).fetchone()
        payload=json.loads(row[0]);payload['autonomous']=row[1]=='AUTONOMOUS_INSTRUCTION'
        result=dict(request['description']);result['response_mode']=response_mode(payload,result)
        from reporting.secretary_presentation import record_description
        return record_description(archive,IncidentStore(root/'runtime/recovery.sqlite3'),request['run'],instruction,payload,result,announce=request.get('announce') is True)
    if action=='checkpoint':
        active_run(archive,request['run']);checkpoint(archive,request['run'],request['checkpoint'])
        return {'state':'YIELDED'}
    if action=='telegram_search_finished':
        from reporting.secretary_controls import finish_search
        return finish_search(archive,root,request)
    if action=='gateway_start_finished':return finish_start(archive,root,request)
    if action=='telegram_search_target':
        active_run(archive,request['run'])
        return {'owner_user_id':config['owner_user_id'],'chat_id':config['chat_id'],'bot_ids':[config['bot_id']]+[b['id'] for b in config.get('allowed_additional_bots',[])]}
    if action=='record_local_tool':
        instruction=active_run(archive,request['run']);step=request['step']
        if (type(step) is not int or not 1<=step<=12 or not (request['request'].get('source')=='local_snapshot' or request['request'].get('source')=='telegram_live' and request['request'].get('name')=='telegram_search')):raise ValueError('Bounded local snapshot evidence required')
        archive.append(request['run']+':tool:'+str(step),'der-secretary',origin='TOOL',kind='READ_ONLY_EXPERIMENT',parent=instruction,payload={'request':request['request'],'result':request['result'],'source':request['request'].get('source')})
        if step==1 and request.get('response_mode','RESEARCH')!='CHAT':progress(IncidentStore(root/'runtime/recovery.sqlite3'),request['run'],'FIRST_TOOL','已处理本机只读工具 '+str(request['request'].get('name'))+'；结果 '+str(request['result'].get('result',request['result'].get('state'))))
        return {'state':'ARCHIVED'}
    if action=='tool':
        instruction=active_run(archive,request['run']);step=request['step']
        if type(step) is not int or not 1<=step<=12:raise ValueError('Bounded tool step required')
        req=request['request']
        if not isinstance(req,dict):raise ValueError('Structured tool request required')
        with closing(archive.connect()) as c:
            prior=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(request['run']+':tool:'+str(step),)).fetchone()
        if prior:
            saved=json.loads(prior[0])
            if saved['request']!=req:raise ValueError('Tool step reused with different content')
            return saved['result']
        if request.get('response_mode')=='CHAT' and req.get('name') in ('research_universe','engineering_proposal','engineering_development_submit'):
            return {'state':'REFUSED','reason':'Conversation cannot create work'}
        # search_records.source selects a registered ledger, not an execution host.
        # Other tools retain the cloud/local-snapshot provenance boundary.
        ledger_source=req.get('name')=='search_records' and req.get('source','work') in ('work','notifications')
        if not ledger_source and req.get('source','cloud')!='cloud':raise ValueError('Cloud tool cannot impersonate local snapshot')
        tool_started_at=time.time();tool_timer=time.monotonic()
        try:
            if req.get('name') in ('broker_query','broker_result'):
                if policy.get('broker_queries_approved') is not True:raise PermissionError('Live broker queries not configured')
                from reporting.secretary_broker import submit,result as broker_result,initialize as broker_initialize
                broker_initialize(archive)
                if req['name']=='broker_query':
                    from reporting.secretary_operations import service_status
                    owner=service_status({'services':['paper-safety']})
                    active=owner['services'][0]['properties'].get('ActiveState')=='active'
                    result=submit(archive,req,run=request['run'],step=step) if active else {'state':'BROKER_OWNER_INACTIVE','reason':'Existing broker owner is stopped; query does not start it or create a second connection','owner_observation':owner}
                else:result=broker_result(archive,req.get('id'))
            elif req.get('name')=='service_status':
                from reporting.secretary_operations import service_status
                result=service_status(req)
            elif req.get('name') in ('cloud_tasks','cloud_task_status','cloud_task_submit'):
                from reporting.secretary_operations import cloud_task
                result=cloud_task(archive,root,req,policy,run=request['run'],step=step,instruction=instruction)
            elif req.get('name') in ('engineering_proposal','engineering_updates'):
                from reporting.engineering_relay import propose,proposals
                result=propose(archive,req,instruction=instruction) if req['name']=='engineering_proposal' else proposals(archive)
            elif req.get('name') in ('engineering_development_context','engineering_development_submit'):
                from reporting.engineering_development import tool as development_tool
                result=development_tool(archive,root,req,policy,instruction=instruction,run=request['run'])
            elif req.get('name')=='research_universe':
                if policy.get('agent_news_selection_approved') is not True:raise PermissionError('Agent news selection not approved')
                from reporting.research_universe import select
                result=select(archive,root,req,run=request['run'],instruction=instruction,step=step)
            else:result=tool(root,req)
        except (OSError,RuntimeError,ValueError,PermissionError,KeyError,TypeError, __import__('sqlite3').Error) as exc:
            result={'state':'REFUSED_OR_UNAVAILABLE','error_type':type(exc).__name__,'message':__import__('reporting.errors',fromlist=['redact']).redact(str(exc)[:200])}
        archive.append(request['run']+':tool:'+str(step),'der-secretary',origin='TOOL',kind='READ_ONLY_EXPERIMENT',parent=instruction,payload={'request':req,'result':result,'tool_started_at':tool_started_at,'tool_finished_at':time.time(),'duration_seconds':round(time.monotonic()-tool_timer,3)})
        if step==1 and request.get('response_mode','RESEARCH')!='CHAT':progress(IncidentStore(root/'runtime/recovery.sqlite3'),request['run'],'FIRST_TOOL','已处理云端只读工具 '+str(req.get('name'))+'；结果 '+str(result.get('result',result.get('state'))))
        return result
    if action=='finish':
        run=request['run'];state=request['state']
        if state=='SUCCEEDED':
            # Repeated finish after an SSH ACK loss reconciles, never resends directly.
            with closing(archive.connect()) as c:
                row=c.execute('SELECT r.instruction,e.payload,e.kind FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.instruction WHERE r.occurrence=?',(run,)).fetchone()
            if row is None:raise ValueError('Reserved run required')
            result=request['result'];text=result['summary']
            if not isinstance(text,str) or not 0<len(text)<=3300:raise ValueError('Bounded public summary required')
            payload=json.loads(row[1]);payload['autonomous']=row[2]=='AUTONOMOUS_INSTRUCTION'
            mode=response_mode(payload,result);result['response_mode']=mode
            if mode!='RESEARCH':result.pop('research',None)
            archive.append(run+':result','der-secretary',origin='MODEL',kind={'CHAT':'CONVERSATION_REPLY','TASK':'TASK_RESULT','RESEARCH':'PUBLIC_RESEARCH_RESULT'}[mode],parent=row[0],payload=result)
            archive.finish_run(run,state=state,result_event=run+':result')
            enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,text,role=mode)
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
            # Re-read ownership inside the shared lock to avoid stale Mac claims at cutover.
            policy=json.loads(policy_path.read_text())
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
