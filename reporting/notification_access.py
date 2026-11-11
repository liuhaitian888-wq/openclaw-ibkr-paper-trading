"""Versioned recipient decisions and append-only application membership.

Display tags are never Telegram visibility permissions or control principals.
Unclassified model prose stays private; public status cards use fixed text.
"""
from contextlib import closing
import json
import re

POLICY = 'notification-access-v1'
PUBLIC_CAPABILITIES = frozenset(('public_research', 'public_progress'))
PRIVATE_KEYS = frozenset(('account', 'account_id', 'cash', 'balance', 'balances', 'positions',
    'holdings', 'executions', 'orders', 'daily_pnl', 'net_liquidation', 'credentials',
    'password', 'bot_token', 'api_key', 'risk_limits', 'gate_changes', 'web_app_url'))
PRIVATE_TEXT = re.compile(r'\b(?:DU[A-Z]?\d{4,}|U\d{5,})\b|(?:本人|我的|账户|帐户).{0,12}(?:资产|现金|持仓|余额|盈亏|损益)|'
    r'(?i:password|api[_ -]?key|bot[_ -]?token)|(?:验证码|二次认证|风控参数|解除暂停|立即生效)', re.S)


def sensitive(payload):
    def walk(value):
        if isinstance(value, dict):
            return any(str(k).lower() in PRIVATE_KEYS and v not in (None, '', [], {}) or walk(v)
                       for k, v in value.items())
        if isinstance(value, list):return any(walk(x) for x in value)
        return isinstance(value, str) and bool(PRIVATE_TEXT.search(value))
    return walk(payload)


def decision(item, config):
    """Pure decision. A model-set public label never overrides private evidence."""
    from .publication_policy import enabled as publication, decision as publication_decision
    if publication(config):
        return publication_decision(item, config)
    p=item['payload']; kind=item['kind']; role=p.get('message_role'); key=item['incident_key']
    result={'policy_version':POLICY, 'audience':'owner', 'reason':'private_or_unclassified', 'public_view':None}
    def choose(audience, reason, view=None):return {**result, 'audience':audience, 'reason':reason, 'public_view':view}
    if kind=='CURRENT_RISK_STATUS':
        if (p.get('grants_trading_permission') is False and isinstance(p.get('current_risk_scope'),str)
                and all(type(p.get(k)) is int and 0<=p[k]<=100 for k in ('recovered_count','unresolved_count'))):
            return choose('group','bound_current_risk_fixed_summary','current_risk_status')
        return choose('hold','invalid_current_risk_summary')
    from .automatic_notifications import enabled as grouped, interactive
    if grouped(config):
        result['policy_version']='automatic-grouped-v1'
        if interactive(item):
            return choose('owner','verified_interaction_or_required_response')
        if kind=='AUTOMATIC_STATUS':
            return choose('group','grouped_automatic_lifecycle','automatic_status')
        # Complete authorized report artifacts, public filings and calendars
        # retain their existing validated views below.
        from .notification_center import public_calendar,public_filing
        if kind not in ('REPORT_BUNDLE','REPORT_SUPPLEMENT') and public_calendar(item) is None and public_filing(item) is None:
            return choose('group','automatic_safe_summary_no_private_mirror',
                          'auth_status' if kind.startswith('AUTH_') or p.get('scope')=='GATEWAY_AUTHENTICATION'
                          else 'activity_status' if kind=='SECRETARY_REPLY' and not p.get('private_notice')
                          else 'ops_status')
    if (p.get('requires_response') is True or p.get('phase')=='OPERATOR'
            or role in ('ACK','CHAT','CONTROL','AUTH') or kind.startswith('AUTH_')
            or p.get('scope')=='GATEWAY_AUTHENTICATION' or p.get('private_notice') is True):
        return choose('owner','interaction_auth_or_control')
    if kind in ('REPORT_BUNDLE','REPORT_SUPPLEMENT'):
        if not p.get('included_reports') and not p.get('png_artifacts'):
            return choose('group','public_report_status','report_status')
        policy=config.get('account_report_policy')
        return choose({'private':'owner','shared_group':'group','hold':'hold'}.get(policy,'hold'),
                      'explicit_account_report_policy:'+str(policy))
    from .notification_center import public_calendar,public_filing
    # These rebuild a public subset; arbitrary prose/metadata is never rendered.
    if public_calendar(item) is not None:return choose('group','fixed_public_calendar','calendar')
    if public_filing(item) is not None:return choose('group','fixed_public_filing','filing')
    if (p.get('data_classification') in ('private_account','security','immediate_control')
            or sensitive(p) or key.startswith(('rejection:','market-session-conflict:','secretary-risk:'))
            or key.startswith('paper-safety:') and key not in ('paper-safety:connection','paper-safety:upstream')):
        return choose('owner','sensitive_content')
    if key in ('paper-safety:connection','paper-safety:upstream','gateway-hang') or p.get('scope')=='MODULE':
        return choose('group','sanitized_operational_status','ops_status')
    if kind=='ENGINEERING_WEEKLY':return choose('group','fixed_engineering_status','engineering_status')
    if role in ('TASK','RESEARCH','PROGRESS','INTELLIGENCE'):
        # Free-form model/tool text is not evidence of public provenance.
        # Its separate public card is generated by the queue, never copied here.
        if p.get('fixed_public_status') is True:
            counts=p.get('public_recovery_counts')
            if isinstance(counts,dict) and set(counts)=={'recovered','unresolved'} and all(type(v) is int and 0<=v<=1000 for v in counts.values()):
                return choose('group','fixed_recovery_counts','risk_status')
            return choose('group','fixed_activity_status','activity_status')
        return choose('owner','unclassified_model_result')
    if kind in ('REPORT_MISSING','REPORT_DELIVERY_STATUS','NOTIFICATION_PUBLIC_RESULT'):
        return choose('group','fixed_delivery_status','report_status')
    return result


def initialize(store):
    with closing(store.connect()) as c,c:
        c.execute('''CREATE TABLE IF NOT EXISTS notification_membership (
          id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          tags TEXT NOT NULL, capabilities TEXT NOT NULL, revoked INTEGER NOT NULL,
          approved_by INTEGER NOT NULL, approved_at REAL NOT NULL, source TEXT NOT NULL)''')
        c.execute('CREATE INDEX IF NOT EXISTS notification_member_lookup ON notification_membership(chat_id,user_id,id)')


def record_member(store, config, *, chat_id, user_id, tags, capabilities, approved_by, source, revoked=False):
    """Called only after native owner control admission; not a model tool.

    Scope is public data only. Account/control access remains exact owner-private.
    Caller supplies the immutable admitted instruction ID as provenance.
    """
    if (approved_by!=config['owner_user_id'] or type(approved_by) is not int
            or chat_id!=config['chat_id'] or type(user_id) is not int or user_id<=0
            or not isinstance(source,str) or not source.startswith(('telegram:','deployment:'))
            or not isinstance(tags,list) or len(tags)>8
            or any(not isinstance(x,str) or not 1<=len(x)<=16 or not x.isprintable() for x in tags)
            or not isinstance(capabilities,list) or not set(capabilities)<=PUBLIC_CAPABILITIES):
        raise PermissionError('Explicit owner approval and bounded public capabilities required')
    initialize(store)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        # Repeat ingestion of the same native instruction cannot create versions.
        old=c.execute('SELECT tags,capabilities,revoked FROM notification_membership WHERE chat_id=? AND user_id=? AND source=?',
                      (chat_id,user_id,source)).fetchone()
        values=(json.dumps(tags,ensure_ascii=False),json.dumps(sorted(set(capabilities))),int(revoked))
        if old:
            if old!=values:raise ValueError('Membership instruction identity reused')
            return
        c.execute('INSERT INTO notification_membership(chat_id,user_id,tags,capabilities,revoked,approved_by,approved_at,source) VALUES(?,?,?,?,?,?,?,?)',
                  (chat_id,user_id,*values,approved_by,store.clock(),source))


def member(store, chat_id, user_id):
    initialize(store)
    with closing(store.connect()) as c:
        row=c.execute('SELECT id,tags,capabilities,revoked,approved_by,approved_at FROM notification_membership WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 1',
                      (chat_id,user_id)).fetchone()
    if not row:return {'tags':['访客'], 'capabilities':[], 'revoked':False, 'version':None}
    return dict(version=row[0],tags=json.loads(row[1]),capabilities=[] if row[3] else json.loads(row[2]),revoked=bool(row[3]),approved_by=row[4],approved_at=row[5])


def allowed(store, chat_id, user_id, capability):
    return capability in PUBLIC_CAPABILITIES and capability in member(store,chat_id,user_id)['capabilities']
