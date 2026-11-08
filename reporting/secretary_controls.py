"""Deterministic owner control commands, outside the model's tool surface."""
from contextlib import closing
import json
import sqlite3
import subprocess
import time
from .telegram_gate import template,apply,reconcile
from .secretary_queue import CONVERSATION,enqueue_reply
from .incidents import IncidentStore


def login_status(root,*,now=None):
    now=time.time() if now is None else now
    try:
        with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.1)) as c:
            row=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        state=json.loads(row[0]) if row else {}
        verified=(state.get('connected') is True and state.get('identity') is True and state.get('upstream_connected') is True
                  and not state.get('dirty',True) and 0<=now-state.get('last_server_reply',0)<=10
                  and {'positions','orders','completed_orders','executions'}==set(state.get('ends',[])))
    except (OSError,sqlite3.Error,ValueError,TypeError):verified=False;state={}
    return {'verified':verified,'account':'DUQ503649','environment':'PAPER','epoch':state.get('epoch'),
            'last_server_reply':state.get('last_server_reply'),'trading_permission':False}


def respond(archive,store,instruction,summary):
    run=instruction+':control'
    archive.reserve_run(run,instruction=instruction,model='PYTHON_CONTROL')
    event=run+':result'
    archive.append(event,CONVERSATION,origin='TOOL',kind='CONTROL_RESULT',parent=instruction,payload={'summary':summary,'source':'deterministic Python control; no model inference'})
    archive.finish_run(run,state='SUCCEEDED',result_event=event)
    enqueue_reply(archive,store,run,summary,role='CONTROL')


def process_controls(archive,root,config,policy=None):
    policy=policy or {}
    reconcile(archive,root);store=IncidentStore(root/'runtime/recovery.sqlite3')
    with closing(archive.connect()) as c:
        rows=c.execute("""SELECT e.occurrence,e.payload FROM secretary_events e WHERE e.kind='CONTROL_INSTRUCTION'
            AND coalesce(json_extract(e.payload,'$.handled_by'),'')!='gate-form' AND NOT EXISTS(SELECT 1 FROM secretary_runs r WHERE r.instruction=e.occurrence) ORDER BY e.rowid LIMIT 5""").fetchall()
    controls=[]
    for instruction,payload in rows:
        text=json.loads(payload)['text'];parts=text.split(maxsplit=1);raw=parts[0];command=raw.split('@')[0]
        aliases_short={'/qmax':'单笔股数','/omax':'单笔金额','/rmax':'单笔风险','/smax':'单股持仓上限','/gmax':'账户总敞口'}
        if command in aliases_short:
            parts=['/gate_set',aliases_short[command]+' '+(parts[1] if len(parts)==2 else '')];command='/gate_set'
        try:
            if '@' in raw and raw.split('@',1)[1]!=config['bot_username']:raise ValueError('Command addressed to another bot')
            if command in ('/start','/help') and len(parts)==1:
                summary='私人秘书已连接。仅owner可调用；私人结果只发你的私聊。\n/inbox 通知收件箱 · /notify 分类与配置 · /preview 编号 预览\n/holdings 持仓 · /ready 门禁 · /gate 风控 · /report 日报回执\n直接发文字即可交给秘书；不需要 /secretary。'
            elif command in ('/inbox','/event','/read','/notify','/preview'):
                from .notification_center import inbox,get_item,mark_read,settings,set_preference,preview
                args=parts[1].split() if len(parts)==2 else []
                if command=='/inbox' and len(args)<=1:summary=inbox(store,args[0] if args else None)
                elif command=='/notify' and not args:summary=settings(store)
                elif command=='/notify' and len(args)==2:summary=set_preference(store,*args)
                elif command=='/read' and len(args)==1:summary=mark_read(store,int(args[0]))
                elif command=='/preview' and len(args)==1:summary=preview(store,config,int(args[0]))
                elif command=='/event' and len(args)==1:
                    from .notification_text import notification_text
                    item=get_item(store,int(args[0]));summary='私人事件详情｜来源：'+item['incident_key']+'\n投递：'+item['status']+'\n'+notification_text(item,store.clock(),max_length=2600)
                else:raise ValueError('用法：/inbox [类别] · /event 编号 · /read 编号 · /preview 编号 · /notify [类别 on或off]')
            elif command in ('/work','/searchlog','/search') and len(parts)==2:
                if command=='/search':
                    from .telegram_search import request_values
                    request={'query':parts[1]};request_values(request)
                    run=instruction+':control';archive.reserve_run(run,instruction=instruction,model='PYTHON_CONTROL')
                    archive.append(run+':requested',CONVERSATION,origin='SYSTEM',kind='TELEGRAM_SEARCH_REQUESTED',parent=instruction,
                        payload={'run':run,'request':request,'target':{'owner_user_id':config['owner_user_id'],'chat_id':config['chat_id'],'bot_ids':[config['bot_id']]+[b['id'] for b in config.get('allowed_additional_bots',[])]}})
                    continue
                else:
                    from .secretary_search import search_records,message
                    summary=message(search_records(root,{'source':'work' if command=='/work' else 'notifications','query':parts[1]}))
            elif command=='/report' and len(parts)==1:
                from .report_delivery_status import display
                from datetime import datetime,timezone
                summary=display(store,datetime.now(timezone.utc))
            elif command=='/engineering' and len(parts)==1:
                from .engineering_relay import proposals
                items=proposals(archive)['items']
                summary='Engineering inbox · '+str(len(items))+' recent proposals\n'+'\n'.join(x['id'][-8:]+' · '+x['proposal']['title']+' · '+x['engineering_status']['state'] for x in items)+'\nShared archive only; no automatic deployment or desktop wakeup.'
            elif command in ('/ready','/holdings') and len(parts)==1:
                from .paper_readiness import collect,message
                summary=message(collect(root),holdings_only=command=='/holdings')
            elif command=='/focus':
                if len(parts)==2:
                    if len(parts[1])>2000:raise ValueError('Research focus limited to 2000 characters')
                    archive.append(instruction+':focus',CONVERSATION,origin='TOOL',kind='USER_FOCUS',parent=instruction,payload={'text':parts[1],'source':'native owner research direction; does not grant tools or trading permission'})
                    summary='长期研究方向已保存，从下一轮自主任务起采用。单次任务继续使用 /secretary。\n'+parts[1]
                else:
                    with closing(archive.connect()) as c:focus=c.execute("SELECT payload FROM secretary_events WHERE kind='USER_FOCUS' ORDER BY rowid DESC LIMIT 1").fetchone()
                    summary='当前长期研究方向：'+(json.loads(focus[0])['text'] if focus else '尚未单独设置；按既有研究授权自主安排。')
            elif command=='/intel' and len(parts)==1:
                reports=[]
                for filename in ('intelligence.latest.json','intelligence-broker.latest.json'):
                    path=root/'runtime'/filename
                    if not path.is_file():reports.append(filename+'：尚无真实采集结果');continue
                    if path.stat().st_size>100000:raise ValueError('Bounded intelligence status required')
                    data=json.loads(path.read_text());reports.append(filename+'：'+str(data.get('state'))+'；采集于 '+str(data.get('observed_at')))
                    if data.get('sources'):reports.extend(str(x['source'])+' '+str(x['state'])+(' HTTP '+str(x['http_status']) if x.get('http_status') else '') for x in data['sources'])
                    if data.get('per_symbol'):reports.extend(x['symbol']+'：'+('已验证本次新闻读取' if x.get('news_usable') else '本次可用性未建立') for x in data['per_symbol'])
                summary='情报源实际状态\n'+'\n'.join(reports)+'\n新闻相关性不证明价格因果，交易门禁独立。'
            elif command=='/gate' and len(parts)==1:
                summary=template(root)
                url=policy.get('limits_web_url')
                if url:
                    from urllib.parse import urlsplit
                    parsed=urlsplit(url)
                    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('HTTPS form URL required')
                    archive.append(instruction+':control:presentation',CONVERSATION,origin='TOOL',kind='CONTROL_PRESENTATION',parent=instruction,payload={'web_app_url':url})
                else:summary+='\n表单入口尚未部署。'
            elif command=='/gate_help' and len(parts)==1:
                summary='交易门禁决定是否允许交易，/ready 显示暂停原因。风控限额是额外数值上限，与现有硬上限取更严值。修改限额不解除PAUSED/MAINTENANCE，不下单或撤单。'
            elif command=='/gate_batch' and len(parts)==2:
                if policy.get('numeric_gate_controls_approved') is not True:raise PermissionError('Numeric controls not approved')
                from .telegram_gate import parse_batch,current
                from .gate_drafts import create_draft,preview_text
                draft=create_draft(archive,root,config['owner_user_id'],current(root)['revision'],parse_batch(parts[1]))
                summary=preview_text(draft)+'\n尚未生效。确认整组应用：\n/gate_confirm '+draft['id']
            elif command=='/gate_confirm' and len(parts)==2:
                if policy.get('numeric_gate_controls_approved') is not True:raise PermissionError('Numeric controls not approved')
                from .gate_drafts import confirm_draft
                data=confirm_draft(archive,root,config['owner_user_id'],parts[1].strip())
                summary='整组已确认 · v'+str(data['revision'])+'\n'+template(root)
            elif command=='/gate_set' and len(parts)==2:
                if policy.get('numeric_gate_controls_approved') is not True:raise PermissionError('Numeric controls not approved')
                from .telegram_gate import current
                aliases={'单笔股数':'max_quantity','单笔金额':'max_order_value','单笔风险':'max_risk_per_order','单股持仓上限':'max_symbol_exposure','账户总敞口':'max_gross_exposure'}
                pair=parts[1].split()
                if len(pair)!=2 or pair[0] not in aliases:raise ValueError('格式：/gate_set 单笔金额 150；发送 /gate 查看字段')
                before=current(root);settings=dict(before['settings']);settings[aliases[pair[0]]]=None if pair[1]=='不限' else pair[1]
                data=apply(archive,root,instruction,{'revision':before['revision'],'settings':settings})
                summary='已生效：'+pair[0]+' = '+pair[1]+'（v'+str(data['revision'])+'）\n'+template(root)
            elif command=='/gate_apply' and len(parts)==2:
                if policy.get('numeric_gate_controls_approved') is not True:raise PermissionError('Numeric controls not approved in deployment policy')
                def invalid(_):raise ValueError('Non-finite JSON rejected')
                request=json.loads(parts[1],parse_constant=invalid)
                data=apply(archive,root,instruction,request)
                summary='Python数值门控已保存，revision='+str(data['revision'])+'。下一次RiskEngine校验立即读取，与既有硬上限取更严值。交易批准、PAUSED、MAINTENANCE、有限测试额度和现有订单均未更改。\n'+template(root)
            elif command in ('/login','/login_assist') and len(parts)==1:
                status=login_status(root)
                if status['verified']:summary='已核验当前Paper账户认证及新鲜完整回读；这不是一次新登录。无需重启Gateway，交易权限保持不变。'
                else:
                    archive.append(instruction+':login-watch',CONVERSATION,origin='SYSTEM',kind='LOGIN_ASSIST',parent=instruction,payload={'requested_at':time.time(),'baseline':status})
                    state=subprocess.run(['systemctl','show','ibkr-gateway.service','-p','ActiveState','--value'],capture_output=True,text=True,timeout=3)
                    if command=='/login_assist' and policy.get('gateway_start_assistance_approved') is True and state.returncode==0 and state.stdout.strip() in ('inactive','failed'):
                        run=instruction+':control';archive.reserve_run(run,instruction=instruction,model='PYTHON_CONTROL')
                        archive.append(run+':requested',CONVERSATION,origin='SYSTEM',kind='GATEWAY_START_REQUESTED',parent=instruction,payload={'run':run})
                        controls.append({'kind':'GATEWAY_START','instruction':instruction,'run':run});continue
                    summary='认证尚未通过新鲜完整回读。已跟踪现有唯一Gateway/IBAutomater owner；需要核对Gateway当前登录/连接界面；若出现手机二次验证，再由你完成。不要在Telegram发送密码或验证码。成功后将自动通知；不会为了检查而重启正常服务。'
            else:raise ValueError('Supported commands: /gate, /gate_apply JSON, /login, /login_assist, /focus text, /intel')
        except (ValueError,PermissionError,OSError,sqlite3.Error) as exc:
            summary='命令未确认生效，请核对：'+str(exc)[:250]+'。现有交易权限和订单不变。'
        respond(archive,store,instruction,summary)
    return controls


def finish_start(archive,root,request):
    run=request['run']
    with closing(archive.connect()) as c:
        row=c.execute("SELECT instruction,state,model FROM secretary_runs WHERE occurrence=?",(run,)).fetchone()
    if row is None or row[1]!='STARTED' or row[2]!='PYTHON_CONTROL':raise ValueError('Reserved control operation required')
    if request.get('accepted') is not True:
        archive.finish_run(run,state='UNKNOWN');return {'state':'UNKNOWN'}
    summary='启动请求已交给现有唯一systemd Gateway owner；认证尚待核验。请完成手机二次验证，取得正确Paper账户的新鲜完整回读后将通知；交易权限不变。'
    event=run+':result';archive.append(event,CONVERSATION,origin='TOOL',kind='CONTROL_RESULT',parent=row[0],payload={'summary':summary})
    archive.finish_run(run,state='SUCCEEDED',result_event=event);enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,summary,role='AUTH')
    return {'state':'SUCCEEDED'}


def tick_login(archive,root):
    status=login_status(root)
    if not status['verified']:return
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT occurrence,parent,payload FROM secretary_events WHERE kind='LOGIN_ASSIST' ORDER BY rowid DESC LIMIT 10").fetchall()
    for occurrence,parent,payload in rows:
        if status['last_server_reply']<=json.loads(payload)['requested_at']:continue
        done=occurrence+':verified'
        with closing(archive.connect()) as c:
            exists=c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(done,)).fetchone()
        if not exists:archive.append(done,CONVERSATION,origin='TOOL',kind='AUTH_VERIFIED',parent=parent,payload=status)
        # Separate deterministic notification identity; never repeats login/start.
        run=done+':notification';archive.reserve_run(run,instruction=parent,model='PYTHON_CONTROL')
        event=done+':message';text='认证成功：已取得正确Paper账户及新鲜完整回读。行情、策略、交易批准仍单独检查，未解除暂停。'
        archive.append(event,CONVERSATION,origin='TOOL',kind='CONTROL_RESULT',parent=parent,payload={'summary':text})
        archive.finish_run(run,state='SUCCEEDED',result_event=event);enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,text,role='AUTH')


def pending_controls(archive):
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT r.occurrence,r.instruction,e.kind,e.payload FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.occurrence||':requested' WHERE r.model='PYTHON_CONTROL' AND r.state='STARTED' AND e.kind IN ('GATEWAY_START_REQUESTED','TELEGRAM_SEARCH_REQUESTED') AND NOT EXISTS(SELECT 1 FROM secretary_events d WHERE d.occurrence=r.occurrence||':dispatch') LIMIT 5").fetchall()
    controls=[]
    for run,instruction,kind,payload in rows:
        if archive.append(run+':dispatch',CONVERSATION,origin='SYSTEM',kind='CONTROL_DISPATCH_STARTED',parent=instruction,payload={'run':run}):
            data=json.loads(payload);controls.append({'kind':'TELEGRAM_SEARCH' if kind=='TELEGRAM_SEARCH_REQUESTED' else 'GATEWAY_START','run':run,'instruction':instruction,**{k:data[k] for k in ('request','target') if k in data}})
    return controls


def finish_search(archive,root,request):
    run=request['run']
    with closing(archive.connect()) as c:
        row=c.execute("SELECT r.instruction,r.model,e.kind FROM secretary_runs r JOIN secretary_events e ON e.occurrence=r.occurrence||':requested' WHERE r.occurrence=?",(run,)).fetchone()
    if not row or row[1:]!=('PYTHON_CONTROL','TELEGRAM_SEARCH_REQUESTED'):raise PermissionError('Reserved owner search required')
    from .telegram_search import message
    from .errors import redact
    result=redact(request['result'])
    if len(json.dumps(result))>50000:raise ValueError('Bounded search result required')
    event=run+':result'
    archive.append(event,CONVERSATION,origin='TOOL',kind='CONTROL_RESULT',parent=row[0],payload={'summary':message(result),'source':'on-demand local Telegram search','search_state':result['state']})
    archive.finish_run(run,state='SUCCEEDED',result_event=event)
    enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,message(result),role='CONTROL')
    return {'state':'ARCHIVED_QUERY_RESULT','search_state':result['state']}


def menu_commands():
    return [('ready','交易门禁：是否允许交易 / 为何暂停'),('gate','风控限额：查看 / 整组编辑'),
            ('holdings','持仓：最新只读回读'),('report','日报：查看投递回执'),
            ('inbox','通知：私人收件箱'),('search','群历史：按关键词检索'),
            ('login','认证：查看连接与登录状态'),('help','秘书帮助：私聊使用说明'),
            ('notify','通知分类与配置'),('preview','通知预览：按编号查看')]
