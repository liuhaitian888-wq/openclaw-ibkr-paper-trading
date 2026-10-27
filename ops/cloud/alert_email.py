"""Opt-in outbox worker. No status-summary replay or execution permission changes."""
import json
import os
from pathlib import Path
import smtplib
import sys
import threading
from contextlib import contextmanager

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


def watch_outbox(root, stopped):
    """Single background SMTP owner for safety monitoring; no broker operations.

    Keep the existing email timer disabled while this owner runs. The shared
    kernel lock also rejects concurrent timer workers. The armed flag remains
    required; no configuration or credentials are ever returned to the caller.
    """
    config = Path.home()/'.config/openclaw/smtp.json'
    runtime = root/'runtime'
    while not stopped.wait(1):
        if not (runtime/'EMAIL_ALERTS_ARMED').is_file():
            continue
        if not config.is_file() or config.stat().st_mode & 0o077:
            continue
        try:
            with monitoring_service('incident-email', root):
                cfg = json.loads(config.read_text())
                co = RecoveryCoordinator(runtime/'recovery.sqlite3')
                store = IncidentStore(co.path)
                while not stopped.is_set() and (runtime/'EMAIL_ALERTS_ARMED').is_file():
                    result = send_one(store, co, cfg, trading_status='Paper安全监控；交易权限另行核验')
                    if result in ('UNKNOWN','BLOCKED_UNKNOWN'):
                        # Unknown notifications remain held, never retried.
                        stopped.wait(1)
                    elif result == 'EMPTY':
                        stopped.wait(1)
        except Exception:
            print('SAFETY_SMTP_WORKER_BLOCKED_OR_UNKNOWN', flush=True)
            stopped.wait(5)


@contextmanager
def safety_email_owner(root, stopped):
    worker = threading.Thread(target=watch_outbox, args=(root, stopped),
                              name='paper-safety-smtp', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=20)
        if worker.is_alive():
            raise RuntimeError('SMTP owner did not stop; do not start a replacement')
