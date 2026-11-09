"""Cloud-only notification owner; no broker interface or model invocation."""
import json
from contextlib import AsyncExitStack
import asyncio
import os
from pathlib import Path
import signal
import sys
import threading
import time
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


async def run_worker():
    os.umask(0o077)
    root = Path.home()/'.local/state/openclaw'
    runtime = root/'runtime'
    armed = runtime/'FEISHU_ALERTS_ARMED'
    smtp_armed = runtime/'BREVO_ALERTS_ARMED'
    if (runtime/'EMAIL_ALERTS_ARMED').exists():
        raise RuntimeError('Legacy SMTP owner must be unarmed before notification ownership')
    config = Path.home()/'.config/openclaw/feishu-alerts.json'
    telegram_armed = runtime/'TELEGRAM_ALERTS_ARMED'
    telegram = telegram_armed.is_file()
    smtp = smtp_armed.is_file() and not telegram
    if smtp:
        if armed.is_file():
            raise RuntimeError('SMTP and Feishu cannot both be armed')
        armed = smtp_armed
        config = Path.home()/'.config/openclaw/smtp.json'
    if telegram:
        if armed.is_file():raise RuntimeError('Feishu must be unarmed before Telegram ownership')
        armed = telegram_armed
        config = Path.home()/'.config/openclaw/telegram.json'
    if not armed.is_file():
        print('FEISHU_ALERTS_NOT_ARMED')
        return 0
    if not smtp and not telegram and smtp_armed.exists():
        raise RuntimeError('Legacy SMTP must be unarmed before Feishu ownership')
    if config.stat().st_mode & 0o077:
        raise PermissionError('Private Feishu configuration must be mode0600')
    cfg = json.loads(config.read_text())
    if telegram:
        from reporting.incident_telegram import validate_config as validate_telegram
        validate_telegram(cfg)
    elif not smtp:
        validate_config(cfg)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    with monitoring_service('incident-email', root):
        coordinator = RecoveryCoordinator(runtime/'recovery.sqlite3')
        coordinator.configure_delivery_transport('telegram' if telegram else 'smtp' if smtp else 'feishu')
        store = IncidentStore(coordinator.path)
        store.enqueue_current_summary('cloud-monitoring-delivery-20261104')
        async with AsyncExitStack() as clients:
            owned_bot=None;private_proof={}
            if telegram:
                from telegram import Bot
                owned_bot=await clients.enter_async_context(Bot(token=cfg['bot_token']))
            report_audit_at=0;recovery_audit_at=0
            while not stopped.is_set() and armed.is_file():
                if ((root/'runtime/FEISHU_ALERTS_ARMED').exists() if (smtp or telegram) else smtp_armed.exists()):
                    raise RuntimeError('Concurrent SMTP arming is not permitted')
                try:
                    if telegram and time.monotonic()-recovery_audit_at>=10:
                        from reporting.notification_reconciliation import recover
                        try:
                            review=await recover(store,coordinator,cfg,owned_bot,root/'reports/financial')
                            coordinator.observe('NOTIFICATION_RECONCILIATION','HEALTHY',freshness='FRESH',enabled=True,
                                reason='Bounded delivery evidence checked; unresolved outcomes never replay',**review)
                        except Exception as exc:
                            coordinator.observe('NOTIFICATION_RECONCILIATION','DEGRADED',freshness='FRESH',enabled=True,reason=type(exc).__name__)
                        recovery_audit_at=time.monotonic()
                    enqueue_authentication_notice(store, datetime.now(timezone.utc))
                    if (runtime/'FINANCIAL_REPORTS_ARMED').is_file():
                        expected = json.loads((Path.home()/'.config/openclaw/paper-observer.json').read_text())['expected_account']
                        enqueue_reports(store, root/'reports/financial', expected, datetime.now(timezone.utc), transport="telegram" if telegram or (runtime/"TELEGRAM_REPORTS_ARMED").is_file() else "smtp" if smtp else "feishu")
                    if time.monotonic()-report_audit_at>=60:
                        from reporting.report_delivery_status import record_status
                        record_status(store,datetime.now(timezone.utc));report_audit_at=time.monotonic()
                    store.enqueue_due_reminders()
                    item=store.claim()
                    if item is None:
                        result='BLOCKED_UNKNOWN' if store.uncertain_notifications() else 'EMPTY'
                    elif telegram or item['payload'].get('delivery_transport')=='telegram':
                        if not telegram and not (runtime/'TELEGRAM_REPORTS_ARMED').is_file():
                            result=store.defer_unsent(item['id'])
                        else:
                            from reporting.incident_telegram import send_one as send_telegram
                            private=Path.home()/'.config/openclaw/telegram.json'
                            if private.stat().st_mode & 0o077:raise PermissionError('Private Telegram configuration required')
                            with private.open() as handle:telegram_cfg=json.load(handle)
                            if owned_bot is not None and telegram_cfg!=cfg:raise RuntimeError('Telegram configuration changed; restart owner for identity verification')
                            result=await send_telegram(store,coordinator,telegram_cfg,report_root=root/'reports/financial',claimed_item=item,owned_bot=owned_bot,private_proof=private_proof)
                    else:
                        result=(send_smtp(store,coordinator,cfg,report_root=root/'reports/financial',claimed_item=item) if smtp
                                else send_one(store,coordinator,cfg,preflight=delivery_preflight,claimed_item=item))
                except Exception:
                    print('NOTIFICATION_DELIVERY_UNKNOWN_REQUIRES_RECONCILIATION', flush=True)
                    await asyncio.sleep(5)
                    continue
                if result not in ('EMPTY', 'BLOCKED_UNKNOWN'):
                    print(result, flush=True)
                if result == 'UNKNOWN':
                    await asyncio.sleep(5)
                elif result in ('EMPTY', 'BLOCKED_UNKNOWN'):
                    await asyncio.sleep(.2)
    return 0


def main():return asyncio.run(run_worker())


if __name__ == '__main__':
    raise SystemExit(main())
