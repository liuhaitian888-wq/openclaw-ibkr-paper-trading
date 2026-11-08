"""Human-readable notifications; durable identities remain in the ledger."""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import math
import re
from zoneinfo import ZoneInfo
from .errors import redact

LOCAL=ZoneInfo('Europe/Berlin')
KINDS={'ALERT':'故障告警','RECOVERY':'恢复通知','CURRENT_SUMMARY':'当前故障摘要',
 'REPORT_BUNDLE':'财务报告','REPORT_SUPPLEMENT':'财务补报',
 'PROTECTION_UNPROTECTED':'保护覆盖缺失','PROTECTION_PARTIALLY_PROTECTED':'保护覆盖不足',
 'PROTECTION_PROTECTION_UNKNOWN':'保护状态待核验','PROTECTION_UNKNOWN':'保护状态待核验',
 'AUTH_EXPECTED_24H':'预计认证窗口提醒（提前24小时）','AUTH_EXPECTED_1H':'预计认证窗口提醒（提前1小时）'}
PROTECTION={'PROTECTED':'已核验保护覆盖','PARTIALLY_PROTECTED':'仅部分持仓有保护',
 'UNPROTECTED':'当前持仓没有已核验的保护覆盖','PROTECTION_UNKNOWN':'暂时无法核验','NO_EXPOSURE':'已确认无持仓、无挂单'}
SCOPES={'PAPER_SAFETY':'Paper账户与订单安全监测','PAPER_MARKET_SESSION_CONFLICT':'Paper行情会话',
 'SYMBOL_MARKET_DATA':'单标的行情','FINANCIAL_REPORTS':'财务报告','GATEWAY_AUTHENTICATION':'Gateway认证'}
TEXT={
 'API_CONNECTION_CLOSED':'API连接已关闭',
 'PROTECTION_UNKNOWN':'当前证据不足，暂时无法确认保护覆盖；不代表保护单已被撤销。',
 'UNPROTECTED':'当前持仓没有已核验的保护覆盖。','PARTIALLY_PROTECTED':'当前仅部分持仓具有已核验的保护覆盖。',
 'PROTECTED':'保护覆盖已重新核验通过。',
 'Complete broker reconciliation confirms no position or open order':'完整券商回读已确认无持仓、无挂单，旧保护故障已关闭。',
 'Exact Paper identity and complete broker readback restored':'正确Paper账户身份与完整券商回读已恢复。',
 'Complete broker position/order/execution readback':'持仓、订单和成交的完整券商回读已恢复。',
 'Broker reconciliation incomplete or failed':'券商回读不完整或对账未通过。',
 'IBKR reported competing market-data session (10197)':'IBKR报告竞争行情会话（10197）；API连接正常也可能无法获取行情。',
 'IBKR upstream and complete Paper readback restored':'IBKR上游连接与完整Paper账户回读已恢复；交易权限与行情门禁仍独立生效。',
 'IBKR upstream lost; preserve authenticated API socket':'IBKR上游连接中断；保留已认证的API连接，等待恢复。',
 'Fresh real-time quotes and complete Paper reconciliation verified':'新鲜实时行情与完整Paper账户回读已核验。',
 'Block new entries; preserve broker orders':'阻止新增风险；保留券商现有订单。',
 'Observe only; preserve existing orders and all trading gates':'持续监测；保留现有订单和交易门禁。',
 'Review broker protection/session; replacement orders require explicit approval':'核对账户、持仓和保护单；补单前需确认实际缺口并单独批准。',
 'Exact Paper identity, complete reconciliation, protection and fresh data/bars':'正确Paper账户、完整券商回读、保护覆盖及新鲜行情/K线分别通过核验。',
 'None':'无需操作，继续观察。'}


def format_time(value):
    try:
        d=datetime.fromtimestamp(value,timezone.utc) if isinstance(value,(int,float)) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if d.tzinfo is None:return d.strftime('%Y-%m-%d %H:%M:%S')+'（时区未核验）'
        return d.astimezone(LOCAL).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError,TypeError,OverflowError,OSError):return '时间未核验'


def display(value):
    # Embedded report text retains its declared timezone; hide subsecond digits only.
    return re.sub(r'(\d{2}:\d{2}:\d{2})\.\d+',r'\1',str(redact(value)))


def batch_name(item):
    key=item['incident_key']
    if key.startswith('paper-safety:protection:'):name=key.rsplit(':',1)[1]+'保护状态'
    elif key=='paper-safety:connection':name='API连接'
    elif key=='paper-safety:upstream':name='券商上游连接'
    elif key.startswith('market-session-conflict:'):name=key.rsplit(':',1)[1]+'行情会话冲突'
    else:name=key
    return display(name)+'·第'+str(item['generation'])+'次故障'


def notification_text(item,started,*,max_length=4000):
    if max_length<256:raise ValueError('Notification budget must retain identity and timing')
    data=item['payload'];kind=item['kind']
    if kind=='SECRETARY_REPLY':
        role=data.get('message_role','RESEARCH')
        if role=='CHAT':return ('买 der｜💬 秘书\n\n'+display(data.get('reason','')))[:max_length]
        label={'TASK':'🛠 任务助手','RESEARCH':'🟦 研究秘书','INTELLIGENCE':'🟪 市场情报','CONTROL':'⚙️ 远程控制','AUTH':'🔐 登录认证','PROGRESS':'🔵 任务进度'}.get(role,'🟦 研究秘书')
        footer='信息不改变交易授权。' if role in ('RESEARCH','INTELLIGENCE') else '现有交易门禁独立生效。' if role in ('CONTROL','AUTH') else '任务结果。' if role=='TASK' else '完成后推送结果。'
        return ('买 der｜'+label+'\n\n'+display(data.get('reason',''))+'\n\n记录 #'+str(item['id'])+' · '+footer)[:max_length]
    name=KINDS.get(kind,'持续故障提醒' if kind.startswith('REMINDER_') else '风险升级' if kind.startswith('ESCALATION_') else kind)
    badge='🟩' if kind=='RECOVERY' else '🟥' if data.get('severity')=='RED' else '🟨' if data.get('severity') is not None else '📄'
    if data.get('scope')=='PAPER_MARKET_SESSION_CONFLICT':name='行情会话竞争恢复' if kind=='RECOVERY' else '行情会话竞争告警'
    elif item.get('incident_key')=='paper-safety:connection':name='API连接恢复' if kind=='RECOVERY' else 'API连接告警'
    elif item.get('incident_key')=='paper-safety:upstream':name='上游连接恢复' if kind=='RECOVERY' else '上游连接告警'
    lines=[badge+' 买 der｜IBKR Paper '+name]
    if data.get('severity') is not None:lines.append({'RED':'重要','YELLOW':'提醒','GREEN':'已恢复'}.get(data['severity'],display(data['severity'])))
    source=data.get('observed_at',data.get('timestamp'))
    if source is not None:lines.append('事件记录时间（柏林）：'+format_time(source))
    for key,label in [('reason','情况'),('scope','影响范围'),('symbol','标的'),('quantity','数量'),
                      ('protection_status','保护状态'),('ib_error_code','IBKR错误码'),
                      ('action_taken','系统已执行'),('user_action','建议你操作'),('recovery_condition','恢复条件')]:
        if data.get(key) is None:continue
        value=data[key]
        if key=='scope':value=SCOPES.get(value,value)
        elif key=='protection_status':value=PROTECTION.get(value,value)
        elif key=='quantity':
            try:
                n=Decimal(str(value))
                if n.is_finite():value=format(n.normalize(),'f')
            except InvalidOperation:pass
        else:value=TEXT.get(value,value) if isinstance(value,str) else value
        if key=='user_action' and kind=='RECOVERY' and data[key]=='Review broker protection/session; replacement orders require explicit approval':value='无需操作，继续观察。'
        lines.append(label+'：'+display(value))
    tail=[]
    if data.get('duration_seconds') is not None:tail.append('本地故障记录持续：'+str(math.floor(data['duration_seconds']))+' 秒（不等于实际停机时长）')
    for key,label in [('scheduled_at','计划发送（柏林）'),('queued_at','排队时间（柏林）')]:
        if data.get(key) is not None:tail.append(label+'：'+format_time(data[key]))
    tail.append('实际发送发起（柏林）：'+format_time(started))
    if data.get('scheduled_at') is not None:tail.append('相对计划延迟：'+str(math.floor(started-data['scheduled_at']))+' 秒')
    if kind not in ('REPORT_BUNDLE','REPORT_SUPPLEMENT'):tail.append('故障批次：'+batch_name(item))
    tail.append('事件编号：'+str(item['id']))
    suffix='\n\n'+'\n\n'.join(tail);body='\n\n'.join(lines);budget=max_length-len(suffix)
    if budget<1:raise ValueError('Timing and identity exceed notification budget')
    if len(body)>budget:body=body[:budget-1].rstrip()+'…'
    return body+suffix
