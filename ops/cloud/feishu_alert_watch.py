"""Cloud-only notification owner; no broker interface or model invocation."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import subprocess
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from reporting.incident_feishu import send_one, validate_config
from reporting.incident_mail import send_one as send_smtp
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.report_schedule import enqueue_reports
from reporting.authentication_schedule import enqueue_authentication_notice
from datetime import datetime, timezone


def delivery_preflight(url):
    # Failure here proves no webhook HTTP request was attempted. DNS success does not prove delivery.
    try:
        return subprocess.run(['/usr/bin/getent','ahosts',urlsplit(url).hostname],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    os.umask(0o077)
    root = Path.home()/'.local/state/openclaw'
    runtime = root/'runtime'
    armed = runtime/'FEISHU_ALERTS_ARMED'
    smtp_armed = runtime/'BREVO_ALERTS_ARMED'
    if (runtime/'EMAIL_ALERTS_ARMED').exists():
        raise RuntimeError('Legacy SMTP owner must be unarmed before notification ownership')
    config = Path.home()/'.config/openclaw/feishu-alerts.json'
    smtp = smtp_armed.is_file()
    if smtp:
        if armed.is_file():
            raise RuntimeError('SMTP and Feishu cannot both be armed')
        armed = smtp_armed
        config = Path.home()/'.config/openclaw/smtp.json'
    if not armed.is_file():
        print('FEISHU_ALERTS_NOT_ARMED')
        return 0
    if not smtp and smtp_armed.exists():
        raise RuntimeError('Legacy SMTP must be unarmed before Feishu ownership')
    if config.stat().st_mode & 0o077:
        raise PermissionError('Private Feishu configuration must be mode0600')
    cfg = json.loads(config.read_text())
    if not smtp:
        validate_config(cfg)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    with monitoring_service('incident-email', root):
        coordinator = RecoveryCoordinator(runtime/'recovery.sqlite3')
        store = IncidentStore(coordinator.path)
        store.enqueue_current_summary('cloud-monitoring-delivery-20261104')
        while not stopped.is_set() and armed.is_file():
            if ((root/'runtime/FEISHU_ALERTS_ARMED').exists() if smtp else smtp_armed.exists()):
                raise RuntimeError('Concurrent SMTP arming is not permitted')
            try:
                enqueue_authentication_notice(store, datetime.now(timezone.utc))
                if (runtime/'FINANCIAL_REPORTS_ARMED').is_file():
                    expected = json.loads((Path.home()/'.config/openclaw/paper-observer.json').read_text())['expected_account']
                    enqueue_reports(store, root/'reports/financial', expected, datetime.now(timezone.utc), transport="smtp" if smtp else "feishu")
                store.enqueue_due_reminders()
                result = (send_smtp(store, coordinator, cfg, report_root=root/"reports/financial") if smtp
                          else send_one(store, coordinator, cfg, preflight=delivery_preflight))
            except Exception:
                print('NOTIFICATION_DELIVERY_UNKNOWN_REQUIRES_RECONCILIATION', flush=True)
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
