"""Observe the existing Paper Gateway journal; never login, restart or send."""
from contextlib import closing
import hashlib
import json
import subprocess
import tempfile


SOURCE = 'gateway-session-journal-v1'
UNIT = 'ibkr-gateway.service'


def read_journal(cursor):
    args = ['journalctl', '-u', UNIT, '--no-pager', '-o', 'json',
            '--output-fields=MESSAGE,__CURSOR,__REALTIME_TIMESTAMP']
    args += ['--after-cursor', cursor, '--no-tail'] if cursor else ['-n', '1']
    # A busy/corrupt source fails visibly without advancing its cursor. Never
    # print raw stdout/stderr, which may contain upstream private messages.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        subprocess.run(args, stdout=output, stderr=errors, timeout=4, check=True)
        if output.tell() > 2_000_000:
            raise ValueError('Session journal batch too large; checkpoint retained')
        output.seek(0)
        rows = [json.loads(line) for line in output if line.strip()]
    if len(rows) > 2000:
        raise ValueError('Session journal batch too large; checkpoint retained')
    return rows


def phase(message):
    # Only exact sanitized owner phases; no usernames, passwords or raw logs.
    text = str(message).strip()
    if text.endswith('Existing session detected') or text.endswith('START_RESULT ExistingSessionDetected') or text.endswith('RESTART_RESULT ExistingSessionDetected'):
        return 'CONFLICT', 'Gateway检测到已有会话；当前证据不能确认另一端身份，也不能证明主动抢占Live。'
    if text.endswith('GATEWAY_EXITED'):
        return 'EXITED', '既有Paper Gateway报告退出；原因尚未核验，不能认定是你的手机登录导致。'
    if text.endswith('SOFT_RESTART_COMPLETED_REQUIRES_API_RECONCILIATION'):
        return 'INITIALIZED', '既有Paper Gateway软重启完成；等待新的账户和订单回读，行情仍单独核验。'
    if text.endswith('START_RESULT None') or text.endswith('RESTART_RESULT None'):
        return 'INITIALIZED', '既有Paper Gateway重新初始化完成；等待新的账户和订单回读，不能据此认定行情已恢复。'
    if text.endswith('Waiting for 2FA confirmation'):
        return 'OPERATOR', 'Gateway已报告正在等待IBKR手机确认，请在本人设备查看原生认证；不要在群内发送密码或验证码。'
    operator_results = ('TwoFactorConfirmationTimeout', 'SecurityDialogDetected', 'LoginFailed',
                        'LoginFailedAccountTasksRequired', 'InitializationTimeout', 'SoftRestartTimeout',
                        'UnknownMessageWindowDetected', 'RestartedProcessNotFound')
    if (text.endswith('RESTART_LIMIT_REQUIRES_OPERATOR') or text.endswith('2FA confirmation timeout')
            or text.endswith('2FA maximum attempts') or text.endswith('Auto-restart token expired')
            or text.endswith('auto-restart login failed')
            or any(text.endswith(prefix + code) for prefix in ('START_RESULT ', 'RESTART_RESULT ')
                   for code in operator_results)):
        return 'OPERATOR', 'Gateway登录恢复需要人工检查或手机验证；没有重新提交登录或抢占请求。'
    return None


def enqueue(c, key, payload):
    c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'AUTH_SESSION_EVENT',?,'PENDING')",
              (key, json.dumps(payload, sort_keys=True)))


def collect(store, root, *, reader=read_journal):
    with closing(store.connect()) as c:
        row = c.execute('SELECT payload FROM incident_cursors WHERE source=?', (SOURCE,)).fetchone()
    before = json.loads(row[0]) if row else None
    rows = reader(before.get('cursor') if before else None)
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError('Bounded native journal batch required')
    for entry in rows:
        if (not isinstance(entry, dict) or not isinstance(entry.get('__CURSOR'), str)
                or not 0 < len(entry['__CURSOR']) <= 1000
                or not isinstance(entry.get('MESSAGE'), str) or len(entry['MESSAGE']) > 65536):
            raise ValueError('Malformed journal evidence; checkpoint retained')
        stamp = float(entry['__REALTIME_TIMESTAMP']) / 1_000_000
        if not 0 <= stamp <= store.clock()+5:
            raise ValueError('Invalid journal timestamp; checkpoint retained')
    count = 0
    with closing(store.connect()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('SELECT payload FROM incident_cursors WHERE source=?', (SOURCE,)).fetchone()
        if current != row:
            raise RuntimeError('Session cursor advanced concurrently; retry read only')
        if before is None:
            state = dict(cursor=rows[-1]['__CURSOR'] if rows else None, pending=[], armed_at=store.clock())
        else:
            state = dict(before)
            state['pending'] = list(before.get('pending', []))
            for entry in rows:
                state['cursor'] = entry['__CURSOR']
                at = float(entry['__REALTIME_TIMESTAMP']) / 1_000_000
                if at < state['armed_at']:
                    continue
                event = phase(entry['MESSAGE'])
                if not event:
                    continue
                key = 'gateway-session:'+hashlib.sha256(entry['__CURSOR'].encode()).hexdigest()[:32]
                label, text = event
                enqueue(c, key, dict(scope='GATEWAY_AUTHENTICATION', reason=text,
                        observed_at=at, phase=label, source='existing Gateway owner journal',
                        action_taken='只记录既有owner事件，未新增登录、重启或会话抢占。',
                        grants_trading_permission=False))
                count += 1
                if label == 'INITIALIZED' and not any(x['key'] == key for x in state['pending']):
                    # A new initialization supersedes unverified earlier epochs.
                    state['pending'] = [dict(key=key, at=at)]
                elif label in ('EXITED', 'CONFLICT', 'OPERATOR'):
                    state['pending'] = []
        if state['pending']:
            from .secretary_controls import login_status
            from .secretary_read import query
            status = login_status(root, now=store.clock())
            try:
                rec = query(root, 'runtime/recovery.sqlite3', "SELECT json_extract(payload,'$.reconciled_at') AS at FROM paper_safety_state WHERE id=1", limit=1).get('rows', [])
                reconciled = float(rec[0]['at']) if rec else 0
            except (ValueError, TypeError, KeyError, __import__('sqlite3').Error):
                reconciled = 0
            pending = state['pending'][0]
            if status['verified'] and pending['at'] < reconciled <= store.clock() and status['last_server_reply'] > pending['at']:
                enqueue(c, pending['key']+':readback', dict(scope='GATEWAY_AUTHENTICATION', phase='ACCOUNT_VERIFIED',
                        observed_at=store.clock(), reason='本次Gateway初始化之后，正确Paper身份及新鲜完整账户／订单回读已核验；行情与交易门禁仍独立。',
                        action_taken='只读核对既有安全owner证据，未发送券商请求。', grants_trading_permission=False))
                state['pending'] = []
                count += 1
        c.execute('INSERT OR REPLACE INTO incident_cursors VALUES(?,?)', (SOURCE, json.dumps(state, sort_keys=True)))
    return count
