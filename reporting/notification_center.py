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
 'report': ('📊', '日报', '日报、缺报、投递回执'),
 'chat': ('💬', '秘书对话', '普通问答与讨论'),
 'task': ('🛠', '委托任务', '明确委托的具体工作'),
 'research': ('🟦', '研究秘书', '课题、实验、证伪、研究进度'),
 'intel': ('🟪', '市场情报', '新闻、财报、SEC、宏观'),
 'control': ('⚙️', '控制', '风控参数、账户查询、工程提案'),
 'fyi': ('📬', '券商FYI', '券商通知原始类别；未接入时不伪造数据'),
 'other': ('📎', '其他', '未分类事件，默认私人可见'),
}
GROUP_KEYS = {'paper-safety:connection': '本地API连接', 'paper-safety:upstream': '券商上游连接'}


def category(item):
    p=item['payload'];k=item['incident_key'];kind=item['kind'];role=p.get('message_role')
    if kind=='SECRETARY_REPLY':
        return {'CHAT':'chat','TASK':'task','RESEARCH':'research','PROGRESS':'research','INTELLIGENCE':'intel','CONTROL':'control','AUTH':'auth'}.get(role,'other')
    if kind.startswith('REPORT_'):return 'report'
    if kind.startswith('AUTH_') or p.get('scope')=='GATEWAY_AUTHENTICATION':return 'auth'
    if p.get('source')=='IBKR_FYI':return 'fyi'
    if k in GROUP_KEYS or k=='gateway-hang':return 'ops'
    if k.startswith(('paper-safety:','rejection:','market-session-conflict:')):return 'risk'
    if p.get('scope')=='MODULE':return 'ops'
    return 'other'


def audience(item, config):
    # Only fixed generic templates can enter a shared group. Never infer public
    # safety from a producer-provided audience/category field.
    if config.get('audience_mode')=='shared_group':
        return 'group' if (item['kind'] in ('REPORT_BUNDLE','REPORT_SUPPLEMENT') or item['incident_key'] in GROUP_KEYS and category(item)=='ops') else 'owner'
    return 'group'


def recipient(item, config):
    if audience(item,config)=='group':return config['chat_id']
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
    """Return exact plain/HTML views. Group text is never derived from payload."""
    cat=category(item);icon,label,_=CATEGORIES[cat];p=item['payload'];kind=item['kind']
    recovered=kind=='RECOVERY';status='已恢复' if recovered else '重要' if p.get('severity')=='RED' else '提醒' if p.get('severity')=='YELLOW' else '更新'
    if audience(item,config)=='group' and config.get('audience_mode')=='shared_group' and cat=='ops':
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
    top=title+'\n'+summary+'\n事件 #'+str(item['id'])+' · /event '+str(item['id'])
    body=html.escape(top)+'\n<blockquote expandable>'+html.escape(detail)+'</blockquote>'
    return {'text':top+'\n'+detail,'html':body,'category':cat,'audience':audience(item,config),'chat_id':recipient(item,config)}


def preview(store,config,ident):
    item=get_item(store,ident);view=render(item,config,store.clock())
    return '仅预览，不执行投递\n发给：'+(('der群（公开日报）' if view['category']=='report' else 'der群（公共运维摘要）') if view['audience']=='group' else '仅你的机器人私聊')+'\n配置：'+('投递开启' if enabled(store,item) else '已静音；保留收件箱')+'\n将发内容（详情折叠）：\n'+view['text'][:2700]


def prior_card(store,item,chat_id):
    if item['kind'] not in ('ALERT','RECOVERY') and not item['kind'].startswith(('REMINDER_','ESCALATION_','PROTECTION_')):return None
    with closing(store.connect()) as c:
        rows=c.execute('''SELECT r.payload FROM notification_outbox n JOIN notification_receipts r ON r.notification_id=n.id
          WHERE n.incident_key=? AND n.generation=? AND n.id<? AND n.status='TELEGRAM_ACCEPTED'
          ORDER BY n.id DESC LIMIT 30''',(item['incident_key'],item['generation'],item['id'])).fetchall()
    for raw, in rows:
        r=json.loads(raw)
        if r.get('chat_id')==chat_id and r.get('card_format')=='compact-v1' and len(r.get('message_ids',[]))==1:return r['message_ids'][0]
    return None
