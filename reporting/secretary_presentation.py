"""Owner-facing task descriptions and progress; technical evidence stays in its archive."""
from contextlib import closing
import hashlib
import json
import re
from .errors import redact


def reference(instruction):
    return 'T'+hashlib.sha256(instruction.encode()).hexdigest()[:8].upper()


def plain(value,limit):
    value=str(redact(value)) if isinstance(value,str) else ''
    value=re.sub(r'telegram:[^\s]+|broker-query:[^\s]+|[a-f0-9]{48,}', '', value)
    value=re.sub(r'/(?:home|Users|opt|tmp|private)/[^\s，。；]+', '', value)
    value=re.sub(r'\b(?:broker_query|broker_result|service_status|search_records|READ_ONLY_RESULT|None)\b', '', value)
    return ' '.join(value.split())[:limit].strip(' ，。；：')


def description(payload,result=None):
    result=result or {};text=payload.get('text','')
    text=re.sub(r'^/(?:research|task|secretary)(?:@\w+)?\s*','',text)
    autonomous=payload.get('autonomous') is True
    title=plain(result.get('task_title'),32) or ('自主研究' if autonomous else plain(text,32)) or '研究任务'
    brief=plain(result.get('task_brief'),120) or plain(result.get('summary'),120) or plain(text,120) or '梳理问题、查证资料并整理结论'
    return {'task_title':title,'task_brief':brief}


def record_description(archive,store,run,instruction,payload,result,*,announce=False):
    mode=result.get('response_mode')
    if mode not in ('TASK','RESEARCH'):return {'state':'NOT_A_TASK'}
    with closing(archive.connect()) as c:
        old=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(run+':description',)).fetchone()
    data=json.loads(old[0]) if old else {**description(payload,result),'task_ref':reference(instruction),'task_mode':mode,'presentation_version':2}
    if old is None:
        archive.append(run+':description','der-secretary',origin='MODEL',kind='TASK_DESCRIPTION',parent=instruction,payload=data)
    if announce:
        label='研究已接下' if mode=='RESEARCH' else '任务已接下'
        body=label+'：'+data['task_title']+'\n简介：'+data['task_brief']+'\n编号：'+data['task_ref']
        encoded=json.dumps({**data,'reason':body,'message_role':'PROGRESS','delivery_transport':'telegram',**({'requires_response':True} if payload.get('autonomous') is not True else {})},ensure_ascii=False)
        with closing(store.connect()) as c,c:
            c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",('secretary-task-start:'+run,encoded))
    return {'state':'ARCHIVED','task_ref':data['task_ref']}


def engineering_progress(connection):
    """Read existing tasks only; never initialize a table or infer a deployment."""
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='secretary_engineering_tasks'").fetchone():
        return {}, {}
    by_run, by_instruction = {}, {}
    rows = connection.execute("SELECT id,instruction,state,payload FROM secretary_engineering_tasks ORDER BY updated DESC,id DESC LIMIT 100").fetchall()
    for identity, instruction, state, payload in rows:
        if not isinstance(identity, str) or not re.fullmatch(r'engineering(?:-development)?:[a-f0-9]{64}', identity):
            continue
        development = identity.startswith('engineering-development:')
        states = {'QUEUED': '开发等待处理' if development else '检查等待处理',
                  'STARTED': '开发处理中' if development else '检查处理中',
                  'UNKNOWN': '开发结果待核对' if development else '检查结果待核对',
                  'PATCH_READY': '补丁与隔离测试完成，等待审阅；尚未部署',
                  'SUCCEEDED': '开发结果待核对' if development else '检查完成；未部署',
                  'FAILED': '开发未完成' if development else '检查未完成',
                  'VALIDATION_FAILED': '隔离校验未通过；尚未部署'}
        item = {'ref': 'T'+identity[-8:].upper(),
                'status': states.get(state, '开发结果待核对' if development else '检查结果待核对'),
                'title': '授权参数校验修复' if development else '只读数据库检查',
                'brief': '检查授权参数类型，生成受限补丁并运行隔离测试' if development else '检查已注册业务数据库的只读证据'}
        by_instruction.setdefault(instruction, item)
        try:
            data = json.loads(payload) if isinstance(payload, str) and len(payload) <= 100000 else {}
        except ValueError:
            data = {}
        run = data.get('requested_by_run') if isinstance(data, dict) else None
        if isinstance(run, str):
            by_run.setdefault(run, item)
    return by_run, by_instruction


def work_status(archive,store,query=''):
    if not isinstance(query,str) or len(query)>200:raise ValueError('Task reference or short keyword required')
    needle=query.strip().lstrip('#').lower()
    with closing(archive.connect()) as c:
        engineering_runs, engineering_instructions = engineering_progress(c)
        rows=c.execute("""SELECT e.occurrence,e.payload,e.kind,r.occurrence,r.state,
          (SELECT payload FROM secretary_events d WHERE d.occurrence=r.occurrence||':description'),
          EXISTS(SELECT 1 FROM secretary_events m WHERE m.parent=e.occurrence AND m.kind='MODEL_STARTED')
          FROM secretary_events e LEFT JOIN secretary_runs r ON r.instruction=e.occurrence
          WHERE e.conversation='der-secretary' AND (e.kind='CHAT_INSTRUCTION' AND e.origin='USER'
            OR e.kind='AUTONOMOUS_INSTRUCTION' AND e.origin='SYSTEM'
            OR e.kind='CONTROL_INSTRUCTION' AND e.origin='USER')
          ORDER BY e.rowid DESC LIMIT 100""").fetchall()
    cards=[]
    for instruction,payload,kind,run,state,saved,model_started in rows:
        child = engineering_runs.get(run) or engineering_instructions.get(instruction)
        if kind == 'CONTROL_INSTRUCTION' and not child:continue
        p=json.loads(payload);p['autonomous']=kind=='AUTONOMOUS_INSTRUCTION'
        data=json.loads(saved) if saved else description(p)
        if child and kind == 'CONTROL_INSTRUCTION':
            data = {'task_title': child['title'], 'task_brief': child['brief']}
        ref=reference(instruction)
        aliases = ref+(' '+child['ref'] if child else '')
        if needle and needle not in (aliases+' '+data['task_title']+' '+data['task_brief']).lower():continue
        status='等待处理' if not state else '正在处理' if state=='STARTED' and model_started else '已接下，等待分析' if state=='STARTED' else '结果待核对' if state=='UNKNOWN' else '未完成' if state=='FAILED' else '答复已生成'
        delivery=''
        if state=='SUCCEEDED':
            with closing(store.connect()) as c:
                n=c.execute("SELECT n.status,r.payload FROM notification_outbox n LEFT JOIN notification_receipts r ON r.notification_id=n.id WHERE n.incident_key=? ORDER BY n.id DESC LIMIT 1",('secretary:'+run,)).fetchone()
            delivery='回复已发送' if n and n[0]=='TELEGRAM_ACCEPTED' and n[1] else '回复发送待确认' if n and n[0] in ('STARTED','UNKNOWN') else '回复等待发送'
        if child:
            status = child['status']
            delivery = ('秘书'+delivery) if delivery else ''
        cards.append(ref+(' / '+child['ref'] if child else '')+'｜'+data['task_title']+'\n简介：'+data['task_brief']+'\n状态：'+status+(' · '+delivery if delivery else ''))
        if len(cards)>=5:break
    from .capacity_engineering import read as capacity_tasks
    labels={'QUEUED_READ_ONLY':'已登记，等待工程owner领取只读诊断','STARTED_READ_ONLY':'工程owner已领取只读诊断',
            'DIAGNOSED':'只读诊断已记录，变更须另行实施','UNKNOWN':'结果待核对，不会自动重做'}
    for item in capacity_tasks(archive.path.parent)['items']:
        if needle and needle not in ('容量 capacity '+item['id']).lower():continue
        cards.insert(0,item['id']+'｜主机容量风险诊断\n状态：'+labels.get(item['state'],'待核对')+'\n未自动启动模型或部署。')
        if len(cards)>=5:break
    return '最近任务\n\n'+'\n\n'.join(cards[:5]) if cards else ('没有找到这个任务。直接发送 /work 可看最近任务。' if needle else '目前没有待显示的任务。直接告诉我你想研究或处理什么即可。')


def compact_message(item):
    p=item['payload'];role=p.get('message_role');body=p.get('reason','')
    if role=='PROGRESS':
        if p.get('presentation_version')!=2:return '任务处理中。\n事件 #'+str(item['id'])
        return str(body)
    label='研究秘书' if role=='RESEARCH' else '任务助手'
    title=plain(p.get('task_title'),32)
    ref=p.get('task_ref')
    return label+('｜'+title if title else '')+'\n'+str(body)+'\n'+('编号：'+ref+' · ' if isinstance(ref,str) and re.fullmatch(r'T[A-F0-9]{8}',ref) else '')+'事件 #'+str(item['id'])
