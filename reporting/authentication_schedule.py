"""Estimated weekly IBKR token invalidation notices; never authenticates or restarts."""
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')


def enqueue_authentication_notice(store, now):
    if now.tzinfo is None:
        raise ValueError('Aware time required')
    local=now.astimezone(NY)
    day=local.date()+timedelta(days=(6-local.weekday()) % 7)
    expected=datetime.combine(day,time(1),NY)
    if expected <= now:
        expected=datetime.combine(day+timedelta(days=7),time(1),NY)
    remaining=(expected.astimezone(timezone.utc)-now.astimezone(timezone.utc)).total_seconds()
    stage='1H' if 0 < remaining <= 3600 else '24H' if remaining <= 86400 else None
    if not stage:
        return False
    key='gateway-weekly-auth:'+expected.date().isoformat()
    payload=dict(severity='YELLOW',scope='GATEWAY_AUTHENTICATION',queued_at=now.timestamp(),
                 scheduled_at=expected.timestamp()-(3600 if stage=='1H' else 86400),
                 reason='预计周度认证窗口：'+expected.isoformat()+'；提前'+stage+'提醒。',
                 action_taken='仅提醒，不自动登录、重启或恢复交易权限。自动重启周内免登录仍需长跑验收。',
                 recovery_condition='用户完成认证并取得新鲜的正确Paper账户回读；行情另外验证。',
                 user_action='请安排人工认证；IBKR也可能提前撤销令牌，具体以实际认证要求为准。',
                 grants_trading_permission=False)
    with closing(store.connect()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) "
                  "VALUES (?,1,?,?,'PENDING')",(key,'AUTH_EXPECTED_'+stage,json.dumps(payload,ensure_ascii=False)))
        return c.execute('SELECT changes()').fetchone()[0] == 1
