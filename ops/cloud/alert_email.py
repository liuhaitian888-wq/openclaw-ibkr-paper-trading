"""Opt-in outbox worker. No status-summary replay or execution permission changes."""
import json
import os
from pathlib import Path
import smtplib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.incidents import IncidentStore
from reporting.incident_mail import send_one
from reporting.recovery import RecoveryCoordinator
from ops.cloud.monitoring_guard import monitoring_service


def main():
    os.umask(0o077)
    root = Path.home() / '.local/state/openclaw'
    runtime = root / 'runtime'
    config = Path.home() / '.config/openclaw/smtp.json'
    if not config.is_file() or not (runtime / 'EMAIL_ALERTS_ARMED').is_file():
        print('EMAIL_NOT_CONFIGURED_OR_ARMED')
        return 0
    if config.stat().st_mode & 0o077:
        raise PermissionError('SMTP configuration must be mode 0600')
    cfg = json.loads(config.read_text())
    with monitoring_service('incident-email', root):
        coordinator = RecoveryCoordinator(runtime / 'recovery.sqlite3')
        store = IncidentStore(coordinator.path)
        status = 'PAUSED/MAINTENANCE标记存在' if ((root / 'PAUSED').exists() or (runtime / 'MAINTENANCE').exists()) else '未验证'
        try:
            outcome = send_one(store, coordinator, cfg, trading_status=status, smtp_factory=smtplib.SMTP)
        except Exception:
            print('SMTP_OUTCOME_UNKNOWN_REQUIRES_RECONCILIATION')
            return 2
        print(outcome)
        return 2 if outcome in ('UNKNOWN', 'BLOCKED_UNKNOWN') else 0


if __name__ == '__main__':
    raise SystemExit(main())
