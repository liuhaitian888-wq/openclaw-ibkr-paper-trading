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
    enqueue_reply(archive,store,run,summary)


def process_controls(archive,root,config,policy=None):
    policy=policy or {}
    reconcile(archive,root);store=IncidentStore(root/'runtime/recovery.sqlite3')
    with closing(archive.connect()) as c:
        rows=c.execute("""SELECT e.occurrence,e.payload FROM secretary_events e WHERE e.kind='CONTROL_INSTRUCTION'
            AND NOT EXISTS(SELECT 1 FROM secretary_runs r WHERE r.instruction=e.occurrence) ORDER BY e.rowid LIMIT 5""").fetchall()
    controls=[]
    for instruction,payload in rows:
        text=json.loads(payload)['text'];parts=text.split(maxsplit=1);raw=parts[0];command=raw.split('@')[0]
        try:
            if '@' in raw and raw.split('@',1)[1]!=config['bot_username']:raise ValueError('Command addressed to another bot')
            if command=='/gate' and len(parts)==1:summary=template(root)
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
                        controls.append({'kind':'GATEWAY_START','instruction':instruction,'run':run});continue
                    summary='认证尚未通过新鲜完整回读。已跟踪现有唯一Gateway/IBAutomater owner；请在IBKR手机完成需要的二次验证，不要在Telegram发送密码或验证码。成功后将自动通知；不会为了检查而重启正常服务。'
            else:raise ValueError('Supported commands: /gate, /gate_apply JSON, /login, /login_assist')
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
    archive.finish_run(run,state='SUCCEEDED',result_event=event);enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,summary)
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
        archive.finish_run(run,state='SUCCEEDED',result_event=event);enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,text)
