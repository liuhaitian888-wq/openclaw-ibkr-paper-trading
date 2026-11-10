"""Hetzner ChatGPT OAuth model owner; no Mac RPC, API key or Telegram transport."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from ops.cloud.secretary_cloud_api import run_once
from reporting.secretary_oauth import oauth_ready,analyze


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    if not (root/'runtime/SECRETARY_CLOUD_OAUTH_ARMED').is_file():raise PermissionError('Cloud OAuth not armed')
    if (root/'runtime/SECRETARY_CLOUD_API_ARMED').exists():raise PermissionError('Refuse duplicate model owners')
    config_path=Path.home()/'.config/openclaw/telegram.json'
    if config_path.stat().st_mode&0o077:raise PermissionError('Private Telegram config required')
    config=json.loads(config_path.read_text());stopped=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopped.set())
    with monitoring_service('secretary-cloud-model',root):
        while not stopped.is_set():
            try:
                if (root/'runtime/SECRETARY_MODEL_DRAIN').exists():
                    stopped.wait(1);continue
                # Same held kernel owner and OAuth home; never concurrent token refresh.
                from ops.cloud.secretary_cloud_api import policy
                from reporting.engineering_tasks import run_once as engineering_once
                state=engineering_once(root,config,policy(root,'cloud_oauth'),home=root/'secretary-oauth')
                if state in ('DISABLED','IDLE','SCOPE_INACTIVE','STARTED_REQUIRES_RECONCILIATION'):
                    state=run_once(root,config,root/'secretary-oauth',owner='cloud_oauth',provider='codex_oauth',auth_check=oauth_ready,inference_backend=analyze)
            except Exception as exc:
                print(json.dumps({'state':'OAUTH_DEPENDENCY_UNAVAILABLE','error_type':type(exc).__name__}),flush=True)
                stopped.wait(15);continue
            if state!='IDLE':print(json.dumps({'state':state,'provider':'codex_oauth','at':time.time()}),flush=True)
            stopped.wait(1)
    return 0

if __name__=='__main__':raise SystemExit(main())
