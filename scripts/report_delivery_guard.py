"""Report-only delivery gate. Never touches trading state or report snapshots."""
from contextvars import ContextVar

DELIVERY_AUTHORIZED = ContextVar("report_delivery_authorized", default=False)

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading.production_paths import STATE_ROOT
from scripts.report_acknowledgement import SUCCESS_STATES

import fcntl
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_DIR = STATE_ROOT


def save(path, payload):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def deliver(report_path, callback, *, state_dir=STATE_DIR, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is None:
        raise ValueError('Timezone-aware datetime required')
    now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / 'delivery.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'LOCKED'}
        path = state_dir / 'delivery.json'
        state = json.loads(path.read_text()) if path.exists() else {'reports': {}}
        records = state['reports']
        recovered = False
        for record in records.values():
            if record['status'] in ('SENDING', 'in_flight'):
                record.update(status='UNKNOWN', requires_review=True,
                              diagnostic='Previous process exited before durable acknowledgement')
                record.setdefault('warning', {'reason': 'previous_process_unacknowledged', 'created_at': now.isoformat(), 'local_only': True})
                record['warning_status'] = 'LOCAL_WARNING'
                recovered = True
        if recovered:
            save(path, state)
        if (state_dir / 'PAUSED').exists():
            return {'status': 'BLOCKED', 'reason': 'delivery_paused'}
        # One-hour initial window; retries are independently spaced and capped.
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1, minutes=1)
        if not start <= now <= end:
            if now > end:
                for record in records.values():
                    if record.get('attempt_date') == now.date().isoformat() and record['status'] not in SUCCESS_STATES:
                        record.setdefault('warning', {'reason': 'delivery_window_expired', 'created_at': now.isoformat(), 'local_only': True})
                for record in records.values():
                    if record.get('warning'): record['warning_status'] = 'LOCAL_WARNING'
                if records: save(path, state)
            return {'status': 'BLOCKED', 'reason': 'outside_schedule'}
        report = json.loads(report_path.read_text())
        trading_date = report.get('trading_date')
        if not trading_date or trading_date == 'MISSING':
            return {'status': 'BLOCKED', 'reason': 'invalid_trading_date'}
        # Schema/version, rendering metadata and hashes are not logical identity.
        report_type = 'daily'
        logical_report_id = 'scheduled-close'
        report_id = f'{report_type}:{trading_date}:{logical_report_id}'
        digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        previous = records.get(report_id)
        if previous:
            if previous['status'] != 'FAILED' or previous.get('attempts', 3) >= 3:
                return {'status': 'DUPLICATE', 'report_id': report_id, 'record': previous}
            if previous.get('attempt_date') != now.date().isoformat():
                return {'status': 'BLOCKED', 'reason': 'retry_window_expired'}
            if now < datetime.fromisoformat(previous['started_at']) + timedelta(minutes=30):
                return {'status': 'BLOCKED', 'reason': 'retry_not_due'}
        elif state.get('last_attempt_date') == now.date().isoformat():
            return {'status': 'DUPLICATE', 'reason': 'another_report_attempted_today'}
        attempts = previous.get('attempts', 0) + 1 if previous else 1
        history = previous.get('history', []) if previous else []
        record = {'status': 'SENDING', 'report_type': report_type, 'logical_report_id': logical_report_id,
                  'report_id': report_id, 'trading_date': trading_date, 'content_hash': digest,
                  'started_at': now.isoformat(), 'trigger_source': 'scheduled_daily',
                  'attempt_date': now.date().isoformat(), 'attempts': attempts, 'attempt_number': attempts,
                  'attempt_time': now.isoformat(), 'pid': os.getpid(), 'ppid': os.getppid(),
                  'executable': sys.executable, 'cwd': str(Path.cwd()), 'image_upload_result': {'status': 'NOT_STARTED'},
                  'webhook_result': {'status': 'NOT_STARTED'}, 'error_code': None,
                  'warning_status': 'NONE', 'history': history}
        records[report_id] = record
        state['last_attempt_date'] = now.date().isoformat()
        save(path, state)
        authorization = DELIVERY_AUTHORIZED.set(True)
        try:
            result = callback()
        except Exception:
            record.update(status='UNKNOWN', requires_review=True, diagnostic='Uncertain delivery exception; reconcile before any manual retry')
            record.setdefault('warning', {'reason': 'manual_review_required', 'created_at': now.isoformat(), 'local_only': True})
            record['warning_status'] = 'LOCAL_WARNING'
            save(path, state)
            raise
        finally:
            DELIVERY_AUTHORIZED.reset(authorization)
        status = {'sent': 'SENT_CONFIRMED', 'SENT': 'SENT_CONFIRMED', 'image_failed': 'FAILED'}.get(result['status'], result['status'])
        if status not in SUCCESS_STATES | {'FAILED', 'UNKNOWN', 'BLOCKED'}:
            status = 'UNKNOWN'
        if status in SUCCESS_STATES:
            complete = result.get('upload_confirmed') is True and result.get('image_key_valid') is True and result.get('message_business_success') is True
            if status == 'SENT_CONFIRMED':
                complete = complete and isinstance(result.get('message_id'), str) and result['message_id'].startswith('om_') and len(result['message_id']) > 3
            else:
                complete = complete and result.get('transport') == 'custom_webhook'
            if not complete:
                status = 'UNKNOWN'
                result = {**result, 'error': 'Missing protocol-specific delivery confirmation'}
        result = {**result, 'status': status}
        record['transport'] = result.get('transport')
        record['status'] = status
        record['message_id'] = result.get('message_id')
        record['image_upload_result'] = result.get('image_upload_result', {'status': 'SUCCESS' if result.get('upload_confirmed') else 'UNKNOWN'})
        record['webhook_result'] = result.get('webhook_result', {'status': 'BUSINESS_SUCCESS' if result.get('message_business_success') else 'UNKNOWN'})
        record['error_code'] = result.get('error_code')
        record['history'].append({'status': status, 'started_at': now.isoformat(), 'attempt': attempts,
                                  'image_upload_result': record['image_upload_result'],
                                  'webhook_result': record['webhook_result'], 'error_code': record['error_code']})
        if status == 'UNKNOWN' or (status == 'FAILED' and attempts >= 3):
            record.setdefault('warning', {'reason': 'manual_review_required', 'created_at': now.isoformat(), 'local_only': True})
        record['warning_status'] = 'LOCAL_WARNING' if record.get('warning') else 'NONE'
        record['requires_review'] = status not in SUCCESS_STATES
        record['diagnostic'] = result.get('error', '')
        record['stage'] = result.get('stage', '')
        record['finished_at'] = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
        if status in SUCCESS_STATES:
            state.update(last_sent_report_id=report_id, content_hash=digest, trading_date=trading_date)
        save(path, state)
        return result


def status_snapshot(state_dir=STATE_DIR):
    path = state_dir / 'delivery.json'
    state = json.loads(path.read_text()) if path.exists() else {'reports': {}}
    return {'paused': (state_dir / 'PAUSED').exists(), 'ledger_exists': path.exists(),
            'manual_review': [r for r in state['reports'].values()
                              if r.get('requires_review') or r['status'] in ('SENDING', 'in_flight')],
            'state': state}


if __name__ == '__main__':
    print(json.dumps(status_snapshot(), indent=2))


def expire_warnings(now, state_dir=STATE_DIR):
    """Local-only end-of-window audit. Never calls a sender or grants retry."""
    now=now.astimezone(ZoneInfo('Asia/Shanghai'))
    path=state_dir/'delivery.json'
    if not path.exists():return
    with (state_dir/'delivery.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        state=json.loads(path.read_text());changed=False
        for record in state['reports'].values():
            if record.get('attempt_date')==now.date().isoformat() and record['status'] not in SUCCESS_STATES and not record.get('warning'):
                record['warning']={'warning_id':'report:'+record['report_id'],'reason':'delivery_window_expired','created_at':now.isoformat(),'local_only':True}
                record['warning_status']='LOCAL_WARNING';changed=True
        if changed:save(path,state)
