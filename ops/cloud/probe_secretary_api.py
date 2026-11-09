"""One explicit native model/low probe; never sends Telegram or reserves old tasks."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.secretary_api import analyze


def main():
    os.umask(0o077);root=Path.home()/'.local/state/openclaw'
    receipt=root/'runtime/secretary-api-probe.json'
    with monitoring_service('secretary-api-probe',root):
        analyze('Return exactly one JSON object: {"summary":"云端模型连接验证成功","tools":[],"response_mode":"CHAT"}. Do not call tools.',
            key_path=Path(os.environ['CREDENTIALS_DIRECTORY'])/'openai_api_key',receipt_path=receipt)
        data=json.loads(receipt.read_text())
        print(json.dumps({k:data[k] for k in ('state','response_id','model','reasoning_effort','usage')}))
    return 0

if __name__=='__main__':raise SystemExit(main())
