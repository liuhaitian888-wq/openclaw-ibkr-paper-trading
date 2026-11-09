"""Single Hetzner model owner. Existing inbox and notification owner retain Telegram."""
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from ops.cloud.secretary_rpc import dispatch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_api import analyze,credential
from reporting.recovery import RecoveryCoordinator
from scripts.run_secretary_bridge import execute
import hashlib


def policy(root):
    value=json.loads((root/'runtime/secretary-policy.json').read_text())
    if (value.get('approved') is not True or value.get('grants_trading_permission') is not False
            or value.get('model_owner')!='cloud_api' or value.get('model')!='gpt-6.1-sol'
            or value.get('reasoning_effort')!='low' or type(value.get('model_owner_since')) not in (int,float)
            or value['model_owner_since']<=0):raise PermissionError('Approved cloud model owner policy required')
    return value


def run_once(root,config,key_path):
    current=policy(root)
    credential(key_path)  # Refuse before reserving a run if the local credential is absent/invalid.
    RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('SECRETARY_API_CREDENTIAL','HEALTHY',freshness='FRESH',
        enabled=True,reason='Private systemd credential readable; API account/model access independently verified')
    def invoke(request):
        # Shared kernel RPC lock also serializes with the retained Mac bridge.
        with redirect_stdout(sys.stderr),monitoring_service('secretary-rpc',root):
            return dispatch(root,request,config,current,caller='cloud_api')
    job=invoke({'action':'poll'}).get('job')
    if job is None:return 'IDLE'
    def inference(prompt,**kwargs):
        archive=SecretaryArchive(root/'agent_secretary.sqlite3')
        from contextlib import closing
        with closing(archive.connect()) as c:
            turns=c.execute("SELECT count(*) FROM secretary_events WHERE parent=? AND kind='MODEL_STARTED' AND occurrence LIKE ?",(job['instruction'],job['run']+':model_started:%')).fetchone()[0]
        identity=hashlib.sha256((job['run']+':'+str(turns)).encode()).hexdigest()
        return analyze(prompt,key_path=key_path,receipt_path=root/'runtime/secretary-api-receipts'/(identity+'.json'),**kwargs)
    try:
        result=execute(job,{'codex':None,'codex_home':None,'empty_dir':None},invoke=invoke,inference=inference,cloud_only=True)
        state=result['state']
        RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('SECRETARY_MODEL','HEALTHY',freshness='FRESH',enabled=True,
            provider='openai_responses',model='gpt-6.1-sol',reasoning_effort='low',reason='Acknowledged cloud inference; reply delivery independently verified')
        return state
    except BaseException as exc:
        try:invoke({'action':'finish','run':job['run'],'state':'UNKNOWN'})
        except Exception:pass  # Durable STARTED survives and cannot be automatically replayed.
        RecoveryCoordinator(root/'runtime/recovery.sqlite3').observe('SECRETARY_MODEL','DEGRADED',freshness='UNKNOWN',enabled=True,
            provider='openai_responses',reason='Cloud inference/archive outcome requires reconciliation',error_type=type(exc).__name__)
        if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        return 'UNKNOWN'


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    if not (root/'runtime/SECRETARY_CLOUD_API_ARMED').is_file():raise PermissionError('Cloud model is not armed')
    config_path=Path.home()/'.config/openclaw/telegram.json'
    if config_path.stat().st_mode&0o077:raise PermissionError('Private Telegram config required')
    config=json.loads(config_path.read_text())
    key_path=Path(os.environ['CREDENTIALS_DIRECTORY'])/'openai_api_key'
    stopped=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopped.set())
    with monitoring_service('secretary-cloud-api',root):
        while not stopped.is_set():
            try:state=run_once(root,config,key_path)
            except Exception as exc:
                print(json.dumps({'state':'DEPENDENCY_UNAVAILABLE','error_type':type(exc).__name__}),flush=True)
                stopped.wait(15);continue
            if state!='IDLE':print(json.dumps({'state':state,'provider':'openai_responses','at':time.time()}),flush=True)
            stopped.wait(1)
    return 0

if __name__=='__main__':raise SystemExit(main())
