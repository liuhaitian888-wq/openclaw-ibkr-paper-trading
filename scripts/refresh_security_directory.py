"""Refresh public symbol metadata only; no broker/account/order interfaces."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.agent_secretary import SecretaryArchive
from reporting.security_directory import refresh


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    with monitoring_service('security-directory-refresh',root):
        try:
            from reporting.storage_policy import preflight
            budget=preflight(root,'PUBLIC_DIRECTORY')
            if not budget['allowed']:
                print(json.dumps(budget,sort_keys=True));return 0
            result=refresh(SecretaryArchive(root/'agent_secretary.sqlite3'),root)
            print(json.dumps({k:result[k] for k in ('revision','count','sources','collected_at','permission_status','grants_trading_permission')},sort_keys=True))
        except Exception as exc:
            print(json.dumps({'state':'DIRECTORY_REFRESH_FAILED','error_type':type(exc).__name__,'prior_directory_preserved':True}));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
