"""Native owner commands only; additive numeric caps cannot arm execution."""
from contextlib import closing
from decimal import Decimal, InvalidOperation
import json
import os
import tempfile
from .database_console import contained

FIELDS=('max_quantity','max_order_value','max_risk_per_order','max_symbol_exposure','max_gross_exposure')
DEFAULT={'max_quantity':1,'max_order_value':'200','max_risk_per_order':'10','max_symbol_exposure':None,'max_gross_exposure':None}


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
    with closing(archive.connect()) as c:
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
    data=current(root)
    payload={'revision':data['revision'],'settings':data['settings']}
    return 'Python数值门控模板（金额单位USD；quantity为整股；0可阻止相应新增请求）\n复制下面整条命令，修改settings内的具体数值后发送：\n/gate_apply '+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n只作用于RiskEngine下一次校验；与已有硬上限取更严值。此命令不能解除PAUSED/MAINTENANCE、批准交易、重置测试额度或修改现有保护单。会话/日历门禁仍独立。'
