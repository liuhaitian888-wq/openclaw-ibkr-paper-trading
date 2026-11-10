"""Click-scoped live checks, executed by existing inbox/model/broker owners."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sqlite3
import time
from .secretary_queue import CONVERSATION, enqueue_reply
from .incidents import IncidentStore

UNIT_LABELS = {'ibkr-secretary-inbox.service':'Telegram收信服务', 'ibkr-secretary-oauth.service':'模型服务',
               'ibkr-paper-safety.service':'券商连接程序', 'ibkr-gateway.service':'IB Gateway券商网关'}
UNITS = tuple(UNIT_LABELS)


def cloud_check(archive, *, runner=subprocess.run):
    started = time.time()
    lines = ['云端现场检查', '检查时间：'+datetime.now(timezone.utc).isoformat(), 'Telegram收信：通过，本次原生命令已到达云端。']
    try:
        with closing(archive.connect()) as c:
            assert c.execute('SELECT 1').fetchone() == (1,)
        lines.append('秘书数据库：通过，现场查询成功。')
    except (OSError, sqlite3.Error) as exc:
        lines.append('秘书数据库：失败（'+type(exc).__name__+'）。')
    try:
        p = runner(['/usr/bin/systemctl', 'show', *UNITS, '--property=Id,ActiveState,SubState', '--no-pager'], capture_output=True, text=True, timeout=3)
        if p.returncode or len(p.stdout)>8000:
            lines.append('服务检查：失败，systemd未返回有效结果。')
        else:
            found = {}
            for block in p.stdout.strip().split('\n\n'):
                fields = dict(x.split('=',1) for x in block.splitlines() if '=' in x)
                if fields.get('Id') in UNITS:found[fields['Id']] = fields
            for unit in UNITS:
                row = found.get(unit, {})
                active = row.get('ActiveState') == 'active' and row.get('SubState') == 'running'
                lines.append(UNIT_LABELS[unit]+'：'+('通过（正在运行）' if active else '失败（'+row.get('ActiveState','未返回')+'/'+row.get('SubState','未返回')+'）'))
    except subprocess.TimeoutExpired:
        lines.append('服务检查：超时（3秒）。')
    except OSError as exc:
        lines.append('服务检查：失败（'+type(exc).__name__+'）。')
    lines.append('以上检查云端程序和秘书数据库；模型连接、券商连接是否成功，请点 /api。耗时 %.1f 秒。'%(time.time()-started))
    return '\n'.join(lines)


def queue_check(archive, root, instruction, group, policy):
    """Reserve one durable run per native click. Duplicate clicks/events never replay."""
    from .secretary_broker import submit
    run = instruction+':live-status'
    if group=='api':
        with closing(archive.connect()) as c:
            count=c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol' AND started_at>=?",(int(archive.clock()//86400)*86400,)).fetchone()[0]
        if count>=24:return '现场模型检查未执行：今日模型任务预算已满。'
    if not archive.reserve_run(run, instruction=instruction, model='gpt-6.1-sol' if group=='api' else 'LIVE_STATUS'):
        return '本次检查已登记，不重复发起。'
    now = archive.clock()
    body = {'run':run, 'group':group, 'queued_at':now, 'deadline':now+65,
            'model_owner':policy.get('model_owner'), 'provider': 'codex_oauth' if policy.get('model_owner')=='cloud_oauth' else 'openai_responses'}
    if policy.get('broker_queries_approved') is True:
        broker=submit(archive, {'area':'snapshot','sections':['quotes'] if group=='market' else ['positions']}, run=run, step=1, wait_seconds=0)
        body['broker_id']=broker.get('id')
        if not body['broker_id']:body['broker_error']='既有券商查询队列繁忙，本次未发送。'
    else:body['broker_error']='券商连接程序尚未获准接受只读查询，本次未发送。'
    archive.append(run+':request', CONVERSATION, origin='SYSTEM', kind='LIVE_STATUS_REQUESTED', parent=instruction, payload=body)
    return '正在现场检查'+('模型与券商连接' if group=='api' else '券商与行情')+'；复用现有连接，最长65秒回报结果。不会重启服务或自动重试。'


def pending(archive):
    with closing(archive.connect()) as c:
        rows=c.execute("SELECT e.occurrence,e.parent,e.payload FROM secretary_events e JOIN secretary_runs r ON r.occurrence=json_extract(e.payload,'$.run') WHERE e.kind='LIVE_STATUS_REQUESTED' AND r.state='STARTED' ORDER BY e.rowid LIMIT 12").fetchall()
    return [(key, parent, json.loads(payload)) for key,parent,payload in rows]


def model_probe(archive, root, key_path, inference, *, owner):
    """Called only by the existing model owner; no competing inference worker."""
    for key, instruction, job in pending(archive):
        if job['group']!='api' or job['model_owner']!=owner:continue
        run=job['run'];now=archive.clock()
        if now>job['deadline']:continue
        attempt=run+':model-attempt'
        with closing(archive.connect()) as c:
            if c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(attempt,)).fetchone():continue
            count=c.execute("SELECT count(*) FROM secretary_events WHERE kind='LIVE_STATUS_MODEL_ATTEMPT' AND recorded_at>=?",(int(now//86400)*86400,)).fetchone()[0]
        if count>=24:
            outcome={'state':'FAILED','reason':'今日现场模型检查达到24次上限，本次未调用。'}
        else:
            if not archive.append(attempt,CONVERSATION,origin='SYSTEM',kind='LIVE_STATUS_MODEL_ATTEMPT',parent=instruction,payload={'run':run,'provider':job['provider']}):continue
            token=hashlib.sha256(run.encode()).hexdigest()[:24]
            try:
                result,usage=inference('Connectivity check only. Return exactly this JSON, with no tools: '+json.dumps({'summary':token,'tools':[]}),
                    key_path=key_path,receipt_path=root/'runtime/secretary-live-status-receipts'/(hashlib.sha256(run.encode()).hexdigest()+'.json'),timeout=25)
                outcome={'state':'PASSED','reason':'本次真实模型调用收到匹配回执。','provider':job['provider']} if result.get('summary')==token and not result.get('tools') else {'state':'FAILED','reason':'模型返回内容未匹配本次检查。'}
            except Exception as exc:
                outcome={'state':'TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else 'FAILED','reason':'本次模型调用未取得成功回执（'+type(exc).__name__+'），不自动重试。'}
        archive.append(run+':model-result',CONVERSATION,origin='TOOL',kind='LIVE_STATUS_MODEL_RESULT',parent=instruction,payload=outcome)
        return True
    return False


def broker_failure(state, reason):
    """Explain the failed stage without presenting queue expiry as a broker rejection."""
    if state in ('READY','STARTED'):
        return '超时：券商连接程序未在65秒内完成查询。'
    reasons = {
        'Broker owner unavailable before query deadline':'券商连接程序未接收本次查询（等待30秒已到期）。',
        'Query expired before broker admission':'券商连接程序接收前，本次查询已过期。',
        'Broker query timed out':'查询已发出，但未及时收到完整券商回执。',
        'Broker connection changed':'查询过程中券商连接发生变化。',
        'Broker owner changed; previous attempt retained, not replayed':'券商连接程序已更换；原查询保留，不自动重发。',
        'Broker request outcome uncertain; not replayed':'原查询结果不确定，已保留，不自动重发。',
        'Broker owner closing; query not replayed':'券商连接程序正在关闭，原查询不自动重发。',
    }
    if reason in reasons:return '失败：'+reasons[reason]
    if isinstance(reason,str) and reason.startswith('BROKER_REQUEST_ERROR_') and reason[len('BROKER_REQUEST_ERROR_'):].isdigit():
        return '失败：券商拒绝本次只读查询（错误码'+reason[len('BROKER_REQUEST_ERROR_'):]+ '）。'
    if isinstance(reason,str) and reason.startswith(('券商连接程序','既有券商查询队列')):
        return '失败：'+reason[:220]
    return '失败：本次没有取得有效券商回执；具体技术原因已保留在检查记录。'


def tick(archive, root):
    from .secretary_broker import result as broker_result
    labels={'PASSED':'通过','FAILED':'失败','TIMEOUT':'超时'}
    for key,instruction,job in pending(archive):
        run=job['run'];now=archive.clock();expired=now>=job['deadline']
        with closing(archive.connect()) as c:
            row=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(run+':model-result',)).fetchone()
        model=json.loads(row[0]) if row else None
        broker=broker_result(archive,job['broker_id']) if job.get('broker_id') else {'state':'UNAVAILABLE','result':{'reason':job.get('broker_error')}}
        broker_done=broker['state'] not in ('READY','STARTED')
        if not expired and (not broker_done or job['group']=='api' and model is None):continue
        lines=['API现场检查结果' if job['group']=='api' else '行情现场检查结果','检查时间：'+datetime.now(timezone.utc).isoformat()]
        if job['group']=='api':
            m=model or {'state':'TIMEOUT','reason':'模型服务未在65秒内完成本次检查（可能正在忙或未运行）。'}
            lines.append('模型连接：'+labels[m['state']]+'；'+m['reason'])
            lines.append('模型连接方式：ChatGPT OAuth（云端登录，无需API密钥）。' if job['provider']=='codex_oauth' else '模型连接方式：OpenAI Responses API。')
        detail=broker.get('result') or {}
        valid=(broker['state']=='SUCCEEDED' and detail.get('source')=='OWNED_LIVE_BROKER_QUERY'
               and type(detail.get('server_reply_at')) in (int,float) and detail['server_reply_at']>=job['queued_at'])
        lines.append('券商连接：'+('通过，本次连接收到IBKR真实回执。' if valid else broker_failure(broker['state'],detail.get('reason'))))
        if job['group']=='market':
            quotes=detail.get('data',{}).get('quotes',{}) if valid else {}
            good=[s for s,q in quotes.items() if isinstance(q,dict) and q.get('data_type')==1 and all(type(q.get(k)) in (int,float) and job['queued_at']<=q[k]<=now and now-q[k]<=10 for k in ('bid_at','ask_at'))]
            lines.append('实时行情：'+('通过，本次检查后收到双边报价：'+', '.join(good[:5]) if good else '未通过：本次窗口没有新鲜实时双边报价。休市、延迟或权限原因需分别核对。'))
        lines.append('本次仅检查连接；交易暂停与维护门禁不变。')
        summary='\n'.join(lines)
        event=run+':result'
        archive.append(event,CONVERSATION,origin='TOOL',kind='LIVE_STATUS_RESULT',parent=instruction,payload={'summary':summary,'broker_state':broker['state']})
        archive.finish_run(run,state='SUCCEEDED',result_event=event)
        enqueue_reply(archive,IncidentStore(root/'runtime/recovery.sqlite3'),run,summary,role='CONTROL')
