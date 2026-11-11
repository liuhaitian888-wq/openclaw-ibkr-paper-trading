"""Owner notification policy and inbox. No broker, model or channel side effects."""
from contextlib import closing
import html
import json

from .notification_text import notification_text, TEXT, display

# Categories describe responsibility, not separate bot credentials.
CATEGORIES = {
 'ops': ('🛠', '运维', '主机、API连接、上游中断、依赖恢复'),
 'risk': ('🟥', '账户风险', '保护覆盖、敞口、对账、订单拒绝'),
 'auth': ('🔐', '认证', '登录到期、二次认证、认证回读'),
 'calendar': ('🕒', '交易时段', '交易所日历、开闭市与休市原因'),
 'engineering': ('🧩', '工程周报', '秘书证据、未收口问题与Codex提示'),
 'report': ('📊', '日报', '日报、缺报、投递回执'),
 'chat': ('💬', '秘书对话', '普通问答与讨论'),
 'task': ('🛠', '委托任务', '明确委托的具体工作'),
 'research': ('🟦', '研究秘书', '课题、实验、证伪、研究进度'),
 'intel': ('🟪', '市场情报', '新闻、财报、SEC、宏观'),
 'control': ('⚙️', '控制', '风控参数、账户查询、工程提案'),
 'fyi': ('📬', '券商FYI', '券商通知原始类别；未接入时不伪造数据'),
 'other': ('📎', '其他', '未分类事件，默认私人可见'),
}
GROUP_KEYS = {'paper-safety:connection': '本地API连接', 'paper-safety:upstream': '券商服务器连接'}


def category(item):
    if item['kind']=='GATEWAY_OPERATOR_ATTENTION':return 'ops'
    if item['kind']=='AUTOMATIC_STATUS':return 'risk' if item['payload'].get('family')=='broker' else 'auth' if item['payload'].get('family')=='authentication' else 'ops'
    if item['kind']=='CURRENT_RISK_STATUS':return 'risk'
    p=item['payload'];k=item['incident_key'];kind=item['kind'];role=p.get('message_role')
    if kind=='SECRETARY_REPLY':
        return {'ACK':'chat','CHAT':'chat','TASK':'task','RESEARCH':'research','PROGRESS':'research','INTELLIGENCE':'intel','CONTROL':'control','AUTH':'auth'}.get(role,'other')
    if kind=='MARKET_SESSION':return 'calendar'
    if kind=='ENGINEERING_WEEKLY':return 'engineering'
    if kind.startswith('REPORT_'):return 'report'
    if kind.startswith('AUTH_') or p.get('scope')=='GATEWAY_AUTHENTICATION':return 'auth'
    if p.get('source')=='IBKR_FYI':return 'fyi'
    if k in GROUP_KEYS or k=='gateway-hang':return 'ops'
    if k.startswith(('paper-safety:','rejection:','market-session-conflict:')):return 'risk'
    if p.get('scope')=='MODULE':return 'ops'
    return 'other'


def public_filing(item):
    """Only bounded public SEC metadata; never model/account/private prose."""
    if item['kind']!='SECRETARY_REPLY' or item['payload'].get('message_role')!='INTELLIGENCE':return None
    p=item['payload'].get('public_filing')
    if not isinstance(p,dict) or p.get('source')!='SEC_EDGAR':return None
    import re
    forms={'10-K':'年度报告，关注全年业务、盈利和风险', '10-Q':'季度报告，关注当季业绩和财务变化',
           '8-K':'重大事项公告；不一定是业绩报告', '4':'内部人士交易申报；不等于看涨或看跌信号',
           '6-K':'境外发行人事项披露', '20-F':'境外发行人年度报告'}
    form=p.get('form');base=form[:-2] if isinstance(form,str) and form.endswith('/A') else form
    symbols=p.get('symbols')
    if (base not in forms or not isinstance(symbols,list) or len(symbols)!=1
            or not isinstance(symbols[0],str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,7}',symbols[0])
            or not isinstance(p.get('entity'),str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',p['entity'])
            or not isinstance(p.get('url'),str) or not re.fullmatch(r'https://www\.sec\.gov/Archives/edgar/data/[0-9]+/'+p['entity'].replace('-','')+r'/[A-Za-z0-9_.-]+',p['url'])):return None
    try:
        from datetime import datetime,timezone
        if type(p.get('published_at')) not in (int,float):return None
        published=datetime.fromtimestamp(p['published_at'],timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):return None
    return ('公开披露｜'+symbols[0]+' '+form+'\n发布时间UTC：'+published+'\n重点看三点：\n'
            +'1. 发生了什么：SEC新增上述文件'+('的修订版' if form.endswith('/A') else '')+'。\n'
            +'2. 文件含义：'+forms[base]+'。\n'
            +'3. 当前缺口：尚未解析正文中的营收、利润或指引，不能判断利好利空；这不是买卖建议。\n来源：'+p['url'])


def public_calendar(item):
    """Rebuild fixed public text; payload prose never crosses the boundary."""
    if item['kind'] != 'MARKET_SESSION':return None
    p=item['payload']
    try:
        from datetime import datetime, timezone
        from .market_clock import snapshot
        observed=p['observed']
        if type(observed) not in (int,float):return None
        state=snapshot(p['venue'],datetime.fromtimestamp(observed,timezone.utc))
        if (p.get('grants_trading_permission') is not False
                or item['incident_key']!='market-session:'+state['occurrence']
                or any(p.get(k)!=state[k] for k in ('phase','source_version','occurrence','expires_at'))):return None
        return state['reason']
    except (KeyError,ValueError,TypeError,OverflowError,OSError):return None


def audience(item, config):
    # Owner-authorized automatic updates share one group; interactive replies
    # and action requests retain the verified secretary destination.
    from .publication_policy import enabled as publication
    if publication(config) or config.get('automatic_updates_to_group') is True:
        from .notification_access import decision
        return decision(item,config)['audience']
    if config.get('audience_mode')=='shared_group':
        return 'group' if (item['kind'] in ('REPORT_BUNDLE','REPORT_SUPPLEMENT') or public_calendar(item) is not None or public_filing(item) is not None or item['incident_key'] in GROUP_KEYS and category(item)=='ops') else 'owner'
    return 'group'


def recipient(item, config):
    target=audience(item,config)
    if target in ('hold','archive'):raise PermissionError('No push destination for archived or held evidence')
    if target=='group':return config['chat_id']
    ident=config.get('owner_private_chat_id')
    if (type(ident) is not int or ident!=config['owner_user_id']
            or config.get('owner_private_verified') is not True):
        raise PermissionError('Verified owner private chat required; never fall back to group')
    return ident


def initialize(store):
    with closing(store.connect()) as c,c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS notification_read_state(notification_id INTEGER PRIMARY KEY,read_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_preferences(category TEXT PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),updated_at REAL NOT NULL);
        ''')


def get_item(store, ident):
    if type(ident) is not int or ident<=0:raise ValueError('Positive event number required')
    with closing(store.connect()) as c:
        r=c.execute('SELECT id,incident_key,generation,kind,payload,status FROM notification_outbox WHERE id=?',(ident,)).fetchone()
    if not r:raise ValueError('未找到该通知')
    return dict(zip(('id','incident_key','generation','kind','payload','status'),r)) | {'payload':json.loads(r[4])}


def critical(item):
    return item['payload'].get('severity')=='RED' or category(item) in ('risk','auth','control') or item['kind']=='RECOVERY'


def stale_schedule(item, now):
    if item['kind'] not in ('MARKET_SESSION','ENGINEERING_WEEKLY'):
        return False
    expiry=item['payload'].get('expires_at')
    return expiry is not None and (type(expiry) not in (int,float) or not __import__('math').isfinite(expiry) or now>=expiry)


def enabled(store,item):
    initialize(store)
    if critical(item):return True
    with closing(store.connect()) as c:r=c.execute('SELECT enabled FROM notification_preferences WHERE category=?',(category(item),)).fetchone()
    return not r or bool(r[0])


def set_preference(store,cat,value):
    if cat not in CATEGORIES or value not in ('on','off'):raise ValueError('格式：/notify research off；类别见 /notify')
    if value=='off' and cat in ('ops','risk','auth','control'):raise ValueError('运维、风险、认证、控制不可关闭；其他类别的红色故障及恢复仍必达')
    initialize(store)
    with closing(store.connect()) as c,c:
        c.execute('INSERT OR REPLACE INTO notification_preferences VALUES(?,?,?)',(cat,int(value=='on'),store.clock()))
    return '已设置 '+cat+' '+value+'；只影响后续主动投递，事件仍留在收件箱。'


def settings(store):
    initialize(store)
    with closing(store.connect()) as c:values=dict(c.execute('SELECT category,enabled FROM notification_preferences'))
    return '通知分类｜/notify 类别 on或off\n'+'\n'.join(k+' '+v[0]+v[1]+' · '+('on' if values.get(k,1) else 'off')+' · '+v[2] for k,v in CATEGORIES.items())+'\n重要故障、恢复、风险、认证和控制不静音。'


def inbox(store,cat=None):
    if cat is not None and cat not in CATEGORIES:raise ValueError('未知分类；发送 /notify 查看分类')
    initialize(store)
    # One current card per logical occurrence; reading old card doesn't mark
    # subsequent status changes read. Bounded query, no historical replay.
    with closing(store.connect()) as c:
        rows=c.execute('''SELECT n.id,n.incident_key,n.generation,n.kind,n.payload,n.status,r.read_at
          FROM notification_outbox n LEFT JOIN notification_read_state r ON r.notification_id=n.id
          WHERE n.id=(SELECT max(x.id) FROM notification_outbox x WHERE x.incident_key=n.incident_key AND x.generation=n.generation)
          ORDER BY n.id DESC LIMIT 200''').fetchall()
    cards=[]
    for r in rows:
        item=dict(zip(('id','incident_key','generation','kind','payload','status'),r[:6]));item['payload']=json.loads(r[4]);kind=category(item)
        if cat and cat!=kind:continue
        cards.append(('● 未读' if r[6] is None else '○ 已读')+' #'+str(r[0])+' '+CATEGORIES[kind][0]+CATEGORIES[kind][1]+' · '+r[3]+' · '+r[5]+'\n来源：'+r[1][:120])
        if len(cards)>=12:break
    return '私人通知收件箱'+(' · '+cat if cat else '')+'\n'+('\n'.join(cards) if cards else '暂无记录')+'\n/event 编号 查看 · /read 编号 标记已读 · /inbox 类别筛选\n已读是本地标记，不代表Telegram阅读回执。'


def mark_read(store,ident):
    get_item(store,ident);initialize(store)
    with closing(store.connect()) as c,c:c.execute('INSERT OR REPLACE INTO notification_read_state VALUES(?,?)',(ident,store.clock()))
    return '#'+str(ident)+' 已标记已读；未来状态更新仍显示未读。'


def render(item,config,at):
    """Return exact plain/HTML views. Automatic updates may include owner-authorized research and task results."""
    cat=category(item);icon,label,_=CATEGORIES[cat];p=item['payload'];kind=item['kind']
    from .publication_policy import enabled as publication
    if publication(config):
        from .notification_access import decision
        route=decision(item,config)
        if route['audience']=='archive':
            raise PermissionError('Archived event has no wire rendering')
        if route['public_view']=='link_status_card':
            from .link_status_card import render as status_text
            text=status_text(item)
            return dict(text=text,html=html.escape(text),category='ops',audience='group',chat_id=recipient(item,config))
        if route['public_view']=='research_result':
            text='研究成果\n'+display(p['reason'])+'\n信息不改变交易授权。'
            return dict(text=text,html=html.escape(text),category='research',audience='group',chat_id=recipient(item,config))
        if route['public_view']=='capacity_action':
            from .capacity import public_status
            text=public_status(item)
            if text is None:raise PermissionError('Bounded fixed capacity numbers required')
            return dict(text=text,html=html.escape(text),category='ops',audience='owner',chat_id=recipient(item,config))
        if route['public_view']=='gateway_action':
            from trading.gateway_readiness import operator_text
            text=operator_text(p)
            return dict(text=text,html=html.escape(text),category='ops',audience='owner',chat_id=recipient(item,config))
    if config.get('automatic_updates_to_group') is True:
        from .notification_access import decision
        route=decision(item,config)
        if route['audience']=='group' and route['public_view']:
            mode=route['public_view']
            if mode=='automatic_status':
                from .automatic_notifications import rendered
                text=rendered(item,at)
            elif mode=='calendar':text=public_calendar(item)
            elif mode=='filing':text=public_filing(item)
            elif mode=='risk_status':
                counts=p['public_recovery_counts']
                text='风险监测恢复摘要｜恢复 '+str(counts['recovered'])+' 项；仍待核验 '+str(counts['unresolved'])+' 项。\n仅状态计数；账户细节在本人私聊，交易权限不变。事件 #'+str(item['id'])
            elif mode=='current_risk_status':
                text='当前保护核验汇总｜已核验 '+str(p['recovered_count'])+' 项；待核验/处理 '+str(p['unresolved_count'])+' 项。\n本次新鲜完整回读；旧三条投递结果未知，已按授权封存且未重发。详细证据留档，按需查询；交易权限不变。事件 #'+str(item['id'])
            else:
                titles={'ops_status':'服务状态已恢复' if kind=='RECOVERY' else '服务状态更新',
                        'auth_status':'认证状态已更新；需要时请在本人私聊完成认证',
                        'activity_status':'研究或任务进度已更新', 'engineering_status':'工程周报已归档',
                        'report_status':'日报生成或投递状态已更新'}
                text=titles[mode]+'｜事件 #'+str(item['id'])+'。'
                if mode=='report_status':text+='仅状态提示，未在群内分享账户数据或附件。'
                else:text+='详细证据已保留，可在本人私聊按需查询。'
            return {'text':text,'html':html.escape(text),'category':cat,'audience':'group','chat_id':recipient(item,config)}
    if kind=='SECRETARY_REPLY' and p.get('message_role') in ('TASK','RESEARCH','PROGRESS') and audience(item,config)=='owner':
        from .secretary_presentation import compact_message
        text=compact_message(item)
        return {'text':text,'html':html.escape(text),'category':cat,'audience':'owner','chat_id':recipient(item,config)}
    recovered=kind=='RECOVERY';status='已恢复' if recovered else '重要' if p.get('severity')=='RED' else '提醒' if p.get('severity')=='YELLOW' else '更新'
    if audience(item,config)=='group' and config.get('audience_mode')=='shared_group' and cat=='ops' and item['incident_key'] in GROUP_KEYS and config.get('automatic_updates_to_group') is not True:
        title=('🟩' if recovered else '🟥')+' #OPS '+status+'｜'+GROUP_KEYS[item['incident_key']]
        summary='连接与完整回读已核验；交易门禁独立。' if recovered else '监测尚未取得完整可用证据，正在跟踪。'
        detail='此群仅显示运维摘要；账户和诊断详情仅限owner私聊。'
    else:
        title=icon+' #'+cat.upper()+' '+status+'｜'+label
        reason=p.get('reason') or '状态已更新'
        if isinstance(reason,str):reason=TEXT.get(reason,reason)
        summary=(display(reason).splitlines() or ['状态已更新'])[0][:150]
        detail=notification_text(item,at,max_length=3300)
    if kind in ('REPORT_BUNDLE','REPORT_SUPPLEMENT'):detail=detail[:520]
    if public_filing(item) is not None and audience(item,config)=='group' and config.get('automatic_updates_to_group') is not True:
        text=public_filing(item)
        return {'text':text,'html':html.escape(text),'category':cat,'audience':'group','chat_id':recipient(item,config)}
    if kind=='MARKET_SESSION' and audience(item,config)=='group' and public_calendar(item) is not None:
        text=public_calendar(item)
        if text is None:raise PermissionError('Fixed public calendar template required')
        return {'text':text,'html':html.escape(text),'category':cat,'audience':'group','chat_id':recipient(item,config)}
    if kind in ('MARKET_SESSION','ENGINEERING_WEEKLY'):
        return {'text':str(p.get('reason','')),'html':html.escape(str(p.get('reason',''))),'category':cat,'audience':audience(item,config),'chat_id':recipient(item,config)}
    if kind=='SECRETARY_REPLY' and p.get('message_role') in ('ACK','CHAT','CONTROL') and audience(item,config)=='owner':
        return {'text':str(p.get('reason','')),'html':html.escape(str(p.get('reason',''))),'category':cat,'audience':'owner','chat_id':recipient(item,config)}
    top=title+'\n'+summary+'\n事件 #'+str(item['id'])+' · /event '+str(item['id'])
    body=html.escape(top)+'\n<blockquote expandable>'+html.escape(detail)+'</blockquote>'
    return {'text':top+'\n'+detail,'html':body,'category':cat,'audience':audience(item,config),'chat_id':recipient(item,config)}


def preview(store,config,ident):
    item=get_item(store,ident);view=render(item,config,store.clock())
    return '仅预览，不执行投递\n发给：'+(('deehub群（公开日报）' if view['category']=='report' else 'deehub群（自动消息）') if view['audience']=='group' else '仅你的机器人私聊')+'\n配置：'+('投递开启' if enabled(store,item) else '已静音；保留收件箱')+'\n将发内容（详情折叠）：\n'+view['text'][:2700]


def prior_card(store,item,chat_id):
    if item['kind']=='LINK_STATUS_CARD':
        from .link_status_card import message_id
        return message_id(store)
    if item['kind']=='AUTOMATIC_STATUS':
        with closing(store.connect()) as c:
            rows=c.execute('''SELECT r.payload FROM notification_outbox n JOIN notification_receipts r ON r.notification_id=n.id
              WHERE n.incident_key=? AND n.id<? AND n.status='TELEGRAM_ACCEPTED' ORDER BY n.id DESC LIMIT 1''',
              (item['incident_key'],item['id'])).fetchall()
        if rows:
            r=json.loads(rows[0][0])
            if r.get('chat_id')==chat_id and r.get('card_format')=='compact-v1' and len(r.get('message_ids',[]))==1:return r['message_ids'][0]
        return None
    if item['kind'] not in ('ALERT','RECOVERY') and not item['kind'].startswith(('REMINDER_','ESCALATION_','PROTECTION_')):return None
    with closing(store.connect()) as c:
        rows=c.execute('''SELECT r.payload FROM notification_outbox n JOIN notification_receipts r ON r.notification_id=n.id
          WHERE n.incident_key=? AND n.generation=? AND n.id<? AND n.status='TELEGRAM_ACCEPTED'
          ORDER BY n.id DESC LIMIT 30''',(item['incident_key'],item['generation'],item['id'])).fetchall()
    for raw, in rows:
        r=json.loads(raw)
        if r.get('chat_id')==chat_id and r.get('card_format')=='compact-v1' and len(r.get('message_ids',[]))==1:return r['message_ids'][0]
    return None
