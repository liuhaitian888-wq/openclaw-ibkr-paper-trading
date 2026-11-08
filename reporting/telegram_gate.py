"""Native owner commands only; additive numeric caps cannot arm execution."""
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
import os
import tempfile
from .database_console import contained

FIELDS=('max_quantity','max_order_value','max_risk_per_order','max_symbol_exposure','max_gross_exposure')
DEFAULT={'max_quantity':1,'max_order_value':'200','max_risk_per_order':'10','max_symbol_exposure':None,'max_gross_exposure':None}


class GateValidationError(ValueError):
    def __init__(self,field_errors):
        self.field_errors=field_errors
        super().__init__('有 '+str(len(field_errors))+' 项需要修改，尚未提交。')


def validate_form(values):
    """Collect field feedback while reusing the unchanged authoritative validator."""
    if not isinstance(values,dict) or set(values)!=set(FIELDS):
        raise GateValidationError({'_form':'请完整填写五项限额，不接受额外字段。'})
    errors={}
    for key in FIELDS:
        value=values[key]
        try:validate({**DEFAULT,key:value})
        except ValueError as exc:
            quantity=key=='max_quantity';unit='股' if quantity else 'USD'
            if value is None or isinstance(value,str) and not value.strip():
                message='请填写单笔股数，当前仅支持整数股数。' if quantity else '请填写金额（USD）。'
            elif str(exc)=='Whole-share quantity required':
                message='当前仅支持整数股数，请输入 0 或正整数；暂不支持小数股。'
            elif str(exc)=='Cap outside supported numeric range':
                message='请输入 0 至 1,000,000,000 的有效数值（'+unit+'）。'
            else:message='请输入有效数字，'+('当前仅支持整数股数。' if quantity else '单位 USD；无需填写单位符号。')
            if key in ('max_symbol_exposure','max_gross_exposure'):message+=' 也可填写“不限”。'
            errors[key]=message
    if errors:raise GateValidationError(errors)
    return validate(values)


def validate(values):
    if not isinstance(values,dict) or set(values)!=set(FIELDS):raise ValueError('Only the five numeric risk cap fields are accepted')
    result={}
    for key,value in values.items():
        if value is None and key in ('max_symbol_exposure','max_gross_exposure'):result[key]=None;continue
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):raise ValueError('Finite nonnegative numeric cap required')
        try:d=Decimal(str(value))
        except InvalidOperation:raise ValueError('Invalid numeric cap')
        if not d.is_finite() or d<0 or d>1_000_000_000:raise ValueError('Cap outside supported numeric range')
        if key=='max_quantity':
            if d!=d.to_integral_value():raise ValueError('Whole-share quantity required')
            result[key]=int(d)
        else:result[key]=str(d)
    return result


def current(root):
    path=contained(root,'runtime/risk-controls.json')
    if not path.exists():
        if contained(root,'runtime/RISK_CONTROLS_REQUIRED').exists():raise ValueError('Required numeric controls missing; fail closed')
        return {'revision':0,'settings':dict(DEFAULT),'state':'NO_OVERRIDE'}
    if path.stat().st_size>4000:raise ValueError('Bounded risk control document required')
    data=json.loads(path.read_text())
    if type(data.get('revision')) is not int or data['revision']<1:raise ValueError('Invalid control revision')
    data['settings']=validate(data['settings'])
    return data


def materialize(root, data):
    path=contained(root,'runtime/risk-controls.json');path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.risk-controls-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(data,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temp):os.unlink(temp)  # Only this newly generated temporary file.


def apply(archive,root,instruction,request):
    if not isinstance(request,dict) or set(request)!= {'revision','settings'} or type(request['revision']) is not int:
        raise ValueError('Exact revision and settings template required')
    settings=validate(request['settings'])
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS secretary_gate_versions (instruction TEXT PRIMARY KEY, revision INTEGER UNIQUE NOT NULL, payload TEXT NOT NULL)')
        authority=c.execute('SELECT origin,kind FROM secretary_events WHERE occurrence=?',(instruction,)).fetchone()
        if authority!=('USER','CONTROL_INSTRUCTION'):raise PermissionError('Native owner control instruction required')
        prior=c.execute('SELECT payload FROM secretary_gate_versions WHERE instruction=?',(instruction,)).fetchone()
        if prior:
            data=json.loads(prior[0])
            if data['settings']!=settings or data['revision']!=request['revision']+1:raise ValueError('Command identity conflict')
        else:
            row=c.execute('SELECT revision,payload FROM secretary_gate_versions ORDER BY revision DESC LIMIT 1').fetchone()
            revision=row[0] if row else current(root)['revision']
            if request['revision']!=revision:raise ValueError('Stale template; fetch /gate again')
            data={'revision':revision+1,'settings':settings,'source_instruction':instruction,'state':'ACTIVE_ADDITIVE_CAPS','grants_trading_permission':False}
            c.execute('INSERT INTO secretary_gate_versions VALUES(?,?,?)',(instruction,revision+1,json.dumps(data,sort_keys=True)))
    # A subsequent poll can materialize the committed version after a crash; no orders execute here.
    reconcile(archive,root)
    return data


def reconcile(archive,root):
    # Serialize committed-version read and materialization across inbox/form/RPC owners.
    with closing(archive.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='secretary_gate_versions'").fetchone():return
        row=c.execute('SELECT payload FROM secretary_gate_versions ORDER BY revision DESC LIMIT 1').fetchone()
        if row:
            latest=json.loads(row[0])
            required=contained(root,'runtime/RISK_CONTROLS_REQUIRED');required.parent.mkdir(parents=True,exist_ok=True)
            required.touch(mode=0o600,exist_ok=True)
            try:matches=current(root)==latest
            except (OSError,ValueError,TypeError):matches=False
            if not matches:materialize(root,latest)


def template(root):
    data=current(root);v=data['settings']
    money=lambda key:'Not set' if v[key] is None else '$'+str(v[key])
    return ('Risk limits · v'+str(data['revision'])+'\n\n'
        +'QMAX · Shares/order: '+str(v['max_quantity'])+'\n'
        +'OMAX · Order value: '+money('max_order_value')+'\n'
        +'RMAX · Risk/order: '+money('max_risk_per_order')+'\n'
        +'SMAX · Symbol exposure: '+money('max_symbol_exposure')+'\n'
        +'GMAX · Gross exposure: '+money('max_gross_exposure')+'\n\n'
        +'整组编辑：点击下方表单，预览后确认。兼容：/gate_batch QMAX=1 OMAX=150 RMAX=8 SMAX=500 GMAX=1200\n\n单项兼容：\n/qmax 1\n/omax 150\n/rmax 8\n/smax 500\n/gmax 1200\n\n'
        +'USD except QMAX. Applied by Python; stricter existing limits still apply.\n'
        +'These commands do not send orders or clear trading approvals/pauses.')


def parse_batch(text):
    import re
    aliases=dict(zip(('QMAX','OMAX','RMAX','SMAX','GMAX'),FIELDS))
    values={}
    for part in text.split():
        match=re.fullmatch(r'(QMAX|OMAX|RMAX|SMAX|GMAX)=(不限|[0-9]+(?:\.[0-9]+)?)',part)
        if not match or match[1] in values:raise ValueError('五项各一次：QMAX=1 OMAX=200 RMAX=10 SMAX=不限 GMAX=不限；金额单位USD')
        values[match[1]]=None if match[2]=='不限' else match[2]
    return validate({aliases[k]:v for k,v in values.items()})
