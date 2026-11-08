"""Bounded Telegram Mini App authentication and five-field API; no Telegram sender."""
import hashlib
import hmac
import json
import time
import secrets
from urllib.parse import parse_qsl
from .telegram_gate import current
from .gate_drafts import create_draft, confirm_draft


def verify_init_data(raw,token,owner,*,now=None):
    now=time.time() if now is None else now
    if not isinstance(raw,str) or not 0<len(raw)<=8192:raise PermissionError('请从owner私聊打开表单')
    pairs=parse_qsl(raw,strict_parsing=True,keep_blank_values=True,max_num_fields=20)
    data=dict(pairs)
    if len(data)!=len(pairs):raise ValueError('Duplicate initData field')
    signature=data.pop('hash','')
    check='\n'.join(k+'='+v for k,v in sorted(data.items()))
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,expected):raise PermissionError('Telegram身份签名无效')
    stamp=int(data['auth_date'])
    if not 0<=now-stamp<=600:raise PermissionError('身份凭证已过期，请重新打开表单')
    user=json.loads(data['user'])
    if type(user.get('id')) is not int or user['id']!=owner or user.get('is_bot',False) is not False:
        raise PermissionError('仅已核验owner可使用')
    return owner


def dispatch(archive,root,config,policy,path,body):
    if config.get('owner_private_verified') is not True or config.get('owner_private_chat_id')!=config['owner_user_id']:
        raise PermissionError('Verified private owner required')
    if not isinstance(body,dict):raise ValueError('JSON object required')
    owner=verify_init_data(body.get('initData'),config['bot_token'],config['owner_user_id'])
    def audit(outcome):
        from .secretary_queue import CONVERSATION
        archive.append('gate-web:'+secrets.token_urlsafe(18),CONVERSATION,origin='SYSTEM',kind='GATE_WEB_AUDIT',
            payload={'owner_user_id':owner,'endpoint':path,'outcome':outcome,'source':'Telegram initData signature verified'})
    if path=='/api/current' and set(body)=={'initData'}:
        from .telegram_gate import reconcile
        reconcile(archive,root)
        result=current(root);audit('READ_ONLY');return result
    if policy.get('numeric_gate_controls_approved') is not True:raise PermissionError('Numeric controls not approved')
    if path=='/api/preview' and set(body)=={'initData','revision','settings'}:
        try:result=create_draft(archive,root,owner,body['revision'],body['settings'])
        except ValueError:
            audit('REJECTED_NO_APPLY');raise
        audit('PREVIEW_ONLY');return result
    if path=='/api/confirm' and set(body)=={'initData','draft'}:
        result=confirm_draft(archive,root,owner,body['draft'])
        from .secretary_controls import respond
        from .incidents import IncidentStore
        instruction='gate-form:'+body['draft']+':confirm'
        # Exact persisted version is returned on duplicate confirmation.
        summary='整组限额确认回执 · v'+str(result['revision'])+'\n'+json.dumps(result['settings'],ensure_ascii=False)+'\n交易门禁、PAUSED/MAINTENANCE保持。'
        respond(archive,IncidentStore(root/'runtime/recovery.sqlite3'),instruction,summary)
        audit('CONFIRMED')
        return result
    raise ValueError('Unsupported exact request')
