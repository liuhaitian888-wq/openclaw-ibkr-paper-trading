"""Cloud-only notification owner; no broker interface or model invocation."""
import json
import os
from pathlib import Path
import signal
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.incident_feishu import send_one, validate_config
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator


def main():
    os.umask(0o077)
    root = Path.home()/'.local/state/openclaw'
    runtime = root/'runtime'
    armed = runtime/'FEISHU_ALERTS_ARMED'
    smtp_armed = runtime/'EMAIL_ALERTS_ARMED'
    config = Path.home()/'.config/openclaw/feishu-alerts.json'
    if not armed.is_file():
        print('FEISHU_ALERTS_NOT_ARMED')
        return 0
    if smtp_armed.exists():
        raise RuntimeError('Legacy SMTP must be unarmed before Feishu ownership')
    if config.stat().st_mode & 0o077:
        raise PermissionError('Private Feishu configuration must be mode0600')
    cfg = json.loads(config.read_text())
    validate_config(cfg)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    with monitoring_service('incident-email', root):
        coordinator = RecoveryCoordinator(runtime/'recovery.sqlite3')
        store = IncidentStore(coordinator.path)
        while not stopped.is_set() and armed.is_file():
            if smtp_armed.exists():
                raise RuntimeError('Concurrent SMTP arming is not permitted')
            try:
                result = send_one(store, coordinator, cfg)
            except RuntimeError:
                print('FEISHU_DELIVERY_UNKNOWN_REQUIRES_RECONCILIATION', flush=True)
                stopped.wait(5)
                continue
            if result not in ('EMPTY', 'BLOCKED_UNKNOWN'):
                print(result, flush=True)
            if result in ('UNKNOWN', 'BLOCKED_UNKNOWN'):
                stopped.wait(5)
            elif result == 'EMPTY':
                stopped.wait(1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
