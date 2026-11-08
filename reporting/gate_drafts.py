"""Owner-bound expiring previews. Activation uses the existing versioned cap store."""
from contextlib import closing
import json
import secrets
import time
from .telegram_gate import current, validate, apply
from .secretary_queue import CONVERSATION


def initialize(archive):
    with closing(archive.connect()) as c,c:
        c.execute('''CREATE TABLE IF NOT EXISTS secretary_gate_drafts (
            id TEXT PRIMARY KEY, owner INTEGER NOT NULL, revision INTEGER NOT NULL,
            settings TEXT NOT NULL, previous TEXT NOT NULL, expires REAL NOT NULL)''')


def create_draft(archive,root,owner,revision,settings,*,now=None):
    now=time.time() if now is None else now
    if type(owner) is not int or owner<=0:raise PermissionError('Exact owner required')
    settings=validate(settings);before=current(root)
    if type(revision) is not int or revision!=before['revision']:raise ValueError('版本已更新，请重新打开表单')
    initialize(archive);ident=secrets.token_urlsafe(24)
    with closing(archive.connect()) as c,c:
        c.execute('INSERT INTO secretary_gate_drafts VALUES (?,?,?,?,?,?)',
                  (ident,owner,revision,json.dumps(settings),json.dumps(before['settings']),now+600))
    return dict(id=ident,revision=revision,settings=settings,previous=before['settings'],expires=now+600)


def confirm_draft(archive,root,owner,ident,*,now=None):
    now=time.time() if now is None else now
    initialize(archive)
    with closing(archive.connect()) as c:
        row=c.execute('SELECT owner,revision,settings,expires FROM secretary_gate_drafts WHERE id=?',(ident,)).fetchone()
        if not row or type(owner) is not int or row[0]!=owner:raise PermissionError('草案身份不匹配')
        instruction='gate-form:'+ident+':confirm'
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='secretary_gate_versions'").fetchone()
        prior=c.execute('SELECT payload FROM secretary_gate_versions WHERE instruction=?',(instruction,)).fetchone() if exists else None
    # A lost response can always reconcile the immutable committed result, even after expiry.
    if prior:
        from .telegram_gate import reconcile
        reconcile(archive,root)
        return json.loads(prior[0])
    if not 0<row[3]-now<=600:raise ValueError('草案已过期，请重新预览')
    archive.append(instruction,CONVERSATION,origin='USER',kind='CONTROL_INSTRUCTION',payload={
        'text':'确认整组应用风控限额','owner_user_id':owner,'draft_id':ident,
        'handled_by':'gate-form','source':'Verified owner explicit preview confirmation'})
    return apply(archive,root,instruction,dict(revision=row[1],settings=json.loads(row[2])))


def preview_text(draft):
    from .telegram_gate import FIELDS
    aliases=('QMAX 股','OMAX USD','RMAX USD','SMAX USD','GMAX USD')
    return ('整组预览 · 当前 v'+str(draft['revision'])+' · 10分钟有效\n'+
            '\n'.join(a+'：'+str(draft['previous'][k] if draft['previous'][k] is not None else '不限')+' → '+str(draft['settings'][k] if draft['settings'][k] is not None else '不限') for a,k in zip(aliases,FIELDS)))
