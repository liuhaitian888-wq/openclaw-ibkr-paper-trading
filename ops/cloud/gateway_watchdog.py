"""Unprivileged Gateway watchdog; polkit grants only the fixed service restart."""
from contextlib import closing
from datetime import datetime
import json
import os
import pwd
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from ops.cloud.paper_safety_watch import gateway_generation
from trading.gateway_recovery import decide, ACCOUNT
from reporting.recovery import RecoveryCoordinator
from reporting.incidents import IncidentStore

ROOT=Path('/home/ibkr/.local/state/openclaw')
UNIT='ibkr-gateway.service'


def bounded_json(path):
    if path.is_symlink() or path.stat().st_size > 1000000:
        raise PermissionError('Bounded non-symlink evidence required')
    return json.loads(path.read_text())


def atomically(path, data):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    temp.chmod(0o600);temp.replace(path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


def unit():
    p=subprocess.run(['systemctl','show',UNIT,'-p','ActiveState','-p','MainPID'],capture_output=True,text=True,timeout=3,check=True)
    return dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)


def evidence(root, now):
    policy=bounded_json(root/'runtime/gateway-recovery-policy.json')
    approved=(policy.get('approved') is True and policy.get('account')==ACCOUNT and policy.get('environment')=='PAPER'
              and policy.get('grants_trading_permission') is False and policy.get('allow_during_maintenance') is True)
    with closing(sqlite3.connect((root/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
        native=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
    original=bounded_json(root/'runtime/paper-observer.latest.json')
    readback={k:original.get(k) for k in ('complete','account_id','environment','server_time','failure_class','gateway_api_handshake')}
    readback['at']=datetime.fromisoformat(original['observed_at']).timestamp()
    # Read only bounded local journal output; never export raw launcher/credential logs.
    p=subprocess.run(['journalctl','-u',UNIT,'--since','-30min','-n','100','--no-pager','-o','cat'],capture_output=True,text=True,timeout=4,check=True)
    text=p.stdout.lower()
    auth=any(x in text for x in ('2fa confirmation timeout','2fa maximum attempts','existing session detected','auto-restart token expired','auto-restart login failed','authenticationfailed','invalid username or password','twofactorconfirmationtimeout','securitydialogdetected','existingsessiondetected','loginfailed'))
    return dict(approved=approved,hold=(root/'runtime/GATEWAY_RECOVERY_HOLD').exists(),
                generation=gateway_generation(),service=unit().get('ActiveState'),native=native,readback=readback,
                identity_mismatch=readback.get('failure_class')=='IDENTITY_MISMATCH',auth_required=auth)


def require_service_user():
    expected=pwd.getpwnam('ibkr').pw_uid
    if expected==0 or os.getuid()!=expected or os.geteuid()!=expected:
        raise PermissionError('Watchdog must run entirely as the ibkr service user')


def evaluate(root=ROOT, *, submit=False):
    require_service_user()
    with monitoring_service('gateway-hang-watchdog',root):
        path=root/'runtime/gateway-recovery-state.json'
        before=bounded_json(path) if path.exists() else {}
        now=time.time();e=evidence(root,now);state,action=decide(before,e,now)
        atomically(path,state) # Reserve durably BEFORE returning any restart request.
        co=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
        healthy=state['reason']=='API_RESPONSIVE'
        co.observe('GATEWAY_RECOVERY','HEALTHY' if healthy else 'RECOVERING' if state.get('operation') in ('STARTED','ACCEPTED') else 'DEGRADED',
                   freshness='FRESH',reason=state['reason'],enabled=True,operation=state.get('operation'),
                   generation=e.get('generation'),grants_trading_permission=False)
        if state.get('operation') in ('STARTED','ACCEPTED','OPERATOR_REQUIRED','RECOVERED'):
            resolved=state['operation']=='RECOVERED'
            text=('Gateway卡死恢复已通过新进程、API心跳及独立账户/订单回读核验。' if resolved else
                  'Gateway持续无响应，已保留一次受限恢复记录；等待恢复回读。' if action=='RESTART_RESERVED' else
                  'Gateway恢复结果仍待核对；不会重复重启，请检查登录或手机验证。')
            if action=='RESTART_RESERVED' or resolved and before.get('operation')!='RECOVERED' or state.get('operation')=='OPERATOR_REQUIRED' and before.get('operation')!='OPERATOR_REQUIRED':
                IncidentStore(co.path).ingest('gateway-hang:'+state['request_id']+':'+state['operation'],'gateway-hang',
                    dict(severity='GREEN' if resolved else 'RED' if state['operation']=='OPERATOR_REQUIRED' else 'YELLOW',scope='GATEWAY_HANG',reason=text,
                         action_taken='仅操作既有ibkr-gateway.service；交易门禁与测试额度保持。',grants_trading_permission=False),resolved=resolved)
        result=dict(action=action,generation=e.get('generation'),request_id=state.get('request_id'),reason=state['reason'])
        # Keep the same kernel lock through reservation, recheck and submission.
        return submit_restart(result,root) if submit else result


def submit_restart(result, root=ROOT):
    require_service_user()
    if result['action']=='RESTART_RESERVED':
        if ((root/'runtime/GATEWAY_RECOVERY_HOLD').exists() or gateway_generation()!=result['generation']
                or unit().get('ActiveState')!='active'):
            return {'action':'HELD_AFTER_RESERVATION','reason':'No replay; reconciliation required'}
        subprocess.run(['/usr/bin/systemctl','--no-ask-password','--no-block','restart',UNIT],
                       capture_output=True,timeout=5,check=True)
        result['action']='RESTART_SUBMITTED_REQUIRES_READBACK'
    return result


def supervise():
    return evaluate(submit=True)


if __name__=='__main__':
    os.umask(0o077)
    try:
        value=evaluate() if sys.argv[1:]==['--evaluate'] else supervise() if not sys.argv[1:] else None
        if value is None:raise ValueError('Fixed invocation required')
        print(json.dumps({**value,'effective_uid':os.geteuid()}))
    except Exception as exc:
        print(json.dumps({'action':'HELD','error_type':type(exc).__name__}));sys.exit(2)
