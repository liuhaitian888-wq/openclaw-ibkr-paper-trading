"""Fixed-target Paper alerts through the existing deehub custom bot."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from reporting.incident_mail import message_for

TARGET = 'deehub'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Feishu redirects are not permitted')


def validate_config(config):
    if config.get('transport') != 'feishu' or config.get('target_name') != TARGET:
        raise ValueError('Existing deehub Feishu target required')
    url = config.get('webhook_url')
    if not isinstance(url, str):
        raise ValueError('Private Feishu webhook required')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('open.feishu.cn', 'open.larksuite.com')
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/open-apis/bot/v2/hook/[A-Za-z0-9_-]+', parsed.path)):
        raise ValueError('Official HTTPS Feishu custom-bot endpoint required')
    if not isinstance(config.get('signing_secret', ''), str):
        raise ValueError('Invalid private signing configuration')


def send_one(store, coordinator, config, *, trading_status='Paper安全监控；交易权限另行核验',
             opener=None, clock=time.time):
    validate_config(config)
    item = store.claim()
    if item is None:
        return 'BLOCKED_UNKNOWN' if store.uncertain_notifications() else 'EMPTY'
    operation = 'notification:outbox:' + str(item['id'])
    try:
        if not coordinator.begin_operation(operation, 'delivery', dict(
                outbox_id=item['id'], notification_kind=item['kind'], transport='feishu', target=TARGET)):
            store.finish(item['id'], 'UNKNOWN')
            return 'UNKNOWN'
        # Reuse evidence fields and redaction, never the old report scheduler.
        message = message_for(item, 'paper-alert@localhost.invalid', trading_status)
        text = message.get_content().replace(
            'SMTP接受不等于收件箱实收；不确定发送不自动重试。',
            '飞书接口接受不等于群内实收；不确定发送不自动重试。')
        prefix = '【通道测试】' if item['payload'].get('test_only') is True else ''
        text = (prefix + '买 der｜IBKR Paper 告警\n' + str(message['Subject']) + '\n' + text
                + '\n通知编号：outbox:' + str(item['id']))
        payload = dict(msg_type='text', content=dict(text=text))
        secret = config.get('signing_secret')
        if secret:
            stamp = str(int(clock()))
            key = (stamp + '\n' + secret).encode()
            payload.update(timestamp=stamp, sign=base64.b64encode(
                hmac.new(key, b'', hashlib.sha256).digest()).decode())
        request = Request(config['webhook_url'], data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        request_open = opener if opener is not None else build_opener(NoRedirect()).open
        with request_open(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError('Feishu HTTP acknowledgement missing')
            result = json.loads(response.read(65536))
            code = result.get('code', result.get('StatusCode'))
            if type(code) is not int or code != 0:
                raise RuntimeError('Feishu business acknowledgement missing')
    except BaseException as error:
        coordinator.finish_operation(operation, 'UNKNOWN')
        store.finish(item['id'], 'UNKNOWN')
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        # Never put the secret webhook URL or transport exceptions into logs.
        raise RuntimeError('Feishu outcome requires reconciliation; never auto-replay') from None
    coordinator.finish_operation(operation, 'SENT_ACCEPTED')
    store.finish(item['id'], 'FEISHU_ACCEPTED')
    return 'FEISHU_ACCEPTED'
