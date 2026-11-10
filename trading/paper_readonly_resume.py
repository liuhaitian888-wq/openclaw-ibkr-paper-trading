"""Explicit one-shot readonly connection recovery; old attempt history is immutable."""
from contextlib import closing
import hashlib,json,time
from .entry_admission import aware_stamp
from .production_diagnostics import context
from reporting.recovery import audit_write_probe

KIND='read_only_connection'
FIELDS={'approved','environment','account','service','identity','commit','branch','code_root','state_root',
        'gateway_generation','prior_attempts','max_connections','issued_at','expires_at','grants_trading_permission'}


def claim_resume(monitor,root,manifest,gateway,*,api_listening,clock=time.time,claim=True):
    path=root/'runtime/paper-readonly-resume-scope.json'
    if not path.exists():return None
    try:
        if path.is_symlink() or path.parent.resolve()!=root/'runtime' or path.stat().st_size>8192 or path.stat().st_mode&0o077:return None
        scope=json.loads(path.read_text())
        if not isinstance(scope,dict):return None
        if manifest.get('monitoring_approved') is not True or manifest.get('environment')!='PAPER' or manifest.get('grants_trading_permission') is not False:return None
        now=clock();actual=context();budget=monitor.state['connection_recovery']
        if (set(scope)!=FIELDS or scope.get('approved') is not True or scope.get('environment')!='PAPER'
                or scope.get('account')!='DUQ503649' or scope.get('service')!='paper-safety'
                or scope.get('grants_trading_permission') is not False or type(scope.get('max_connections')) is not int or scope['max_connections']!=1
                or type(scope.get('prior_attempts')) is not int or scope['prior_attempts']!=4 or budget.get('attempts')!=4
                or api_listening is not True or not gateway or scope['gateway_generation']!=gateway or budget.get('gateway_generation')!=gateway
                or now<budget.get('not_before',0)
                or not isinstance(scope.get('identity'),str) or not scope['identity'].startswith('paper-readonly-storage-recovery-') or len(scope['identity'])>160
                or not 0<=now-aware_stamp(scope['issued_at'])<=300
                or not now<aware_stamp(scope['expires_at'])<=aware_stamp(scope['issued_at'])+300):return None
        for name in ('commit','branch','code_root','state_root'):
            if not actual.get(name) or actual[name]!=scope[name] or actual[name]!=manifest.get(name):return None
        gateway_manifest=json.loads((root/'runtime/gateway-automater-deployment.json').read_text())
        if gateway_manifest.get('approved') is not True or gateway_manifest.get('environment')!='PAPER' or gateway_manifest.get('grants_trading_permission') is not False:return None
        if any(gateway_manifest.get(k)!=actual[k] for k in ('commit','branch','code_root','state_root')):return None
        if str(root.resolve())!=actual['state_root']:return None
        if monitor.persistence_circuit.blocked:
            failure=monitor.persistence_circuit.failure
            if failure.get('requires_operator') or failure.get('marker_write_failed'):return None
        with closing(monitor.coordinator.connect()) as c:
            if c.execute('SELECT 1 FROM operation_attempts WHERE identity=?',(scope['identity'],)).fetchone():return None
            if c.execute("SELECT 1 FROM operation_attempts WHERE kind=? AND status IN ('STARTED','UNKNOWN')",(KIND,)).fetchone():return None
        if not claim:return dict(eligible=True)
        audit_write_probe(monitor.audit._path)
        encoded=json.dumps(scope,sort_keys=True,allow_nan=False);digest=hashlib.sha256(encoded.encode()).hexdigest()
        payload=dict(scope=scope,scope_sha256=digest,claimed_at=now,prior_attempts=4,grants_trading_permission=False)
        if not monitor.coordinator.begin_operation(scope['identity'],KIND,payload):return None
        with closing(monitor.coordinator.connect()) as c:
            row=c.execute('SELECT kind,status,payload FROM operation_attempts WHERE identity=?',(scope['identity'],)).fetchone()
        if row!=(KIND,'STARTED',json.dumps(payload,sort_keys=True)):return None
        budget['explicit_resume_identity']=scope['identity']
        return dict(identity=scope['identity'],gateway_generation=gateway,scope_sha256=digest,confirmed=False,transport_started=False)
    except (OSError,ValueError,KeyError,TypeError):return None


def confirm_resume(monitor,resume,connected_since,gateway):
    if resume['confirmed']:return True
    if gateway!=resume['gateway_generation']:return False
    if not monitor.validate_connection(connected_since,connection_generation=monitor.state.get('api_protocol',{}).get('connection'),preserve_attempt_history=True):return False
    monitor.coordinator.finish_operation(resume['identity'],'CONFIRMED')
    with closing(monitor.coordinator.connect()) as c:
        row=c.execute('SELECT kind,status FROM operation_attempts WHERE identity=?',(resume['identity'],)).fetchone()
    if row!=(KIND,'CONFIRMED'):
        monitor.persistence_circuit.block(RuntimeError('Readonly recovery confirmation differs'),'resume_confirmation')
        return False
    resume['confirmed']=True
    return True


def retain_failed_resume(monitor,resume):
    if resume is None or resume['confirmed']:return
    status='UNKNOWN' if resume['transport_started'] else 'FAILED_FINAL'
    with closing(monitor.coordinator.connect()) as c,c:
        c.execute("UPDATE operation_attempts SET status=? WHERE identity=? AND kind=? AND status='STARTED'",(status,resume['identity'],KIND))
