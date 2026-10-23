"""One bounded outbox attempt through existing durable side-effect ownership."""
from datetime import datetime
from email.message import EmailMessage
import hashlib
import smtplib
import ssl
from zoneinfo import ZoneInfo

from .errors import redact

RECIPIENT = 'liuhaitian888@hotmail.com'


def message_for(item, sender, trading_status):
    data = item['payload']
    severity = data.get('severity', 'YELLOW')
    message = EmailMessage()
    message['From'] = sender
    message['To'] = RECIPIENT
    message['Subject'] = f'[IBKR Paper {severity}] {item["kind"]}'
    identity = hashlib.sha256((item['incident_key'] + ':' + str(item['generation']) + ':' + item['kind']).encode()).hexdigest()
    message['Message-ID'] = f'<openclaw-{identity}@paper.invalid>'
    queued = data.get('queued_at')
    local_time = datetime.fromtimestamp(queued, ZoneInfo('Europe/Berlin')).isoformat() if queued is not None else '历史时间未验证'
    def field(*keys):
        for key in keys:
            if data.get(key) is not None:
                return str(redact(data[key]))
        return '未提供'
    lines = [
        'IBKR Paper 业务通知；不授予或恢复交易权限。',
        '记录时间（Europe/Berlin）：' + local_time,
        '源事件时间：' + field('timestamp', 'observed_at'),
        '严重程度：' + severity,
        '通知类型：' + item['kind'],
        '标的：' + field('symbol'),
        '订单类型：' + field('order_type'),
        'IBKR错误码：' + field('ib_error_code'),
        '原因：' + field('reason', 'ib_error_message'),
        '影响范围：' + field('scope'),
        '已采取行动：' + field('action_taken'),
        '交易状态：' + trading_status + '；此发送器不验证实时交易READY。',
        '用户操作：' + field('user_action'),
        '恢复条件：' + field('recovery_condition'),
        '本地故障记录持续秒数：' + field('duration_seconds'),
        'SMTP接受不等于收件箱实收；不确定发送不自动重试。',
    ]
    message.set_content('\n'.join(lines))
    return message


def send_one(store, coordinator, config, *, trading_status='未验证', smtp_factory=smtplib.SMTP):
    # Validate before reserving; never print configuration or SMTP exception data.
    for key in ('host', 'sender', 'username', 'relay_password'):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError('Incomplete private SMTP configuration')
    port = int(config.get('port', 587))
    item = store.claim()
    if item is None:
        return 'BLOCKED_UNKNOWN' if store.uncertain_notifications() else 'EMPTY'
    operation = 'notification:outbox:' + str(item['id'])
    try:
        if not coordinator.begin_operation(operation, 'delivery', dict(outbox_id=item['id'], notification_kind=item['kind'])):
            store.finish(item['id'], 'UNKNOWN')
            return 'UNKNOWN'
        message = message_for(item, config['sender'], trading_status)
        with smtp_factory(config['host'], port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(config['username'], config['relay_password'])
            refused = smtp.send_message(message, to_addrs=[RECIPIENT])
            if refused:
                raise RuntimeError('Recipient not accepted')
    except BaseException:
        # Crash between any two commits remains STARTED/UNKNOWN and is never replayed.
        coordinator.finish_operation(operation, 'UNKNOWN')
        store.finish(item['id'], 'UNKNOWN')
        raise
    coordinator.finish_operation(operation, 'SENT_ACCEPTED')
    store.finish(item['id'], 'SMTP_ACCEPTED')
    return 'SMTP_ACCEPTED'
