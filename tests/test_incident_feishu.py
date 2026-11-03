from contextlib import closing
import base64
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.incident_feishu import send_one, validate_config
from ops.cloud import feishu_alert_watch


class FeishuIncidentTests(unittest.TestCase):
    def setup_queue(self, path):
        store = IncidentStore(path, clock=lambda: 1793689200)
        coordinator = RecoveryCoordinator(path)
        store.ingest('fault', 'market-session-conflict:PFE', dict(
            severity='RED', symbol='PFE', ib_error_code=10197,
            reason='Competing market-data session', grants_trading_permission=False))
        return store, coordinator

    def config(self):
        return dict(transport='feishu', target_name='deehub',
                    webhook_url='https://open.feishu.cn/open-apis/bot/v2/hook/offline-fixture',
                    signing_secret='offline-signing-fixture')

    def response(self, body=None):
        response = Mock()
        response.status = 200
        response.read.return_value = json.dumps(body if body is not None else {'code': 0}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_signed_acceptance_unblocks_recovery_and_does_not_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, coordinator = self.setup_queue(Path(tmp)/'state.sqlite3')
            store.ingest('recovery', 'market-session-conflict:PFE', dict(severity='GREEN'), resolved=True)
            opener = Mock(return_value=self.response())
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener,
                                     clock=lambda: 1793689200), 'FEISHU_ACCEPTED')
            request = opener.call_args.args[0]
            body = json.loads(request.data)
            expected = base64.b64encode(hmac.new(
                b'1793689200\noffline-signing-fixture', b'', hashlib.sha256).digest()).decode()
            self.assertEqual(body['sign'], expected)
            self.assertEqual(body['msg_type'], 'text')
            text = body['content']['text']
            self.assertIn('10197', text)
            self.assertIn('不授予或恢复交易权限', text)
            self.assertNotIn('SMTP', text)
            self.assertNotIn('offline-signing-fixture', text)
            self.assertIn('outbox:1', text)
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'FEISHU_ACCEPTED')
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'EMPTY')
            self.assertEqual(opener.call_count, 2)

    def test_rejection_invalid_response_and_timeout_are_held_across_restart(self):
        for failure in ({'code': 19024}, {}, {'code': False}, {'code': '0'}, 'timeout'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'state.sqlite3'
                store, coordinator = self.setup_queue(path)
                store.ingest('recovery', 'market-session-conflict:PFE', {'severity': 'GREEN'}, resolved=True)
                opener = Mock(side_effect=TimeoutError('secret-url') if failure == 'timeout' else None,
                              return_value=self.response(failure if isinstance(failure, dict) else None))
                with self.assertRaisesRegex(RuntimeError, 'reconciliation') as caught:
                    send_one(store, coordinator, self.config(), opener=opener)
                self.assertNotIn('secret-url', str(caught.exception))
                self.assertEqual(send_one(IncidentStore(path), RecoveryCoordinator(path), self.config(),
                                         opener=opener), 'BLOCKED_UNKNOWN')
                self.assertEqual(opener.call_count, 1)
                self.assertEqual(coordinator.uncertainties()[0][2], 'UNKNOWN')

    def test_fixed_target_and_https_endpoint_validated_before_claim(self):
        changes = [dict(target_name='someone-else'), dict(transport='smtp'),
                   dict(webhook_url='http://open.feishu.cn/open-apis/bot/v2/hook/fixture'),
                   dict(webhook_url='https://example.invalid/open-apis/bot/v2/hook/fixture'),
                   dict(webhook_url='https://open.feishu.cn/open-apis/bot/v2/hook/fixture?secret=x')]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                store, coordinator = self.setup_queue(Path(tmp)/'state.sqlite3')
                opener = Mock()
                with self.assertRaises(ValueError):
                    send_one(store, coordinator, self.config() | change, opener=opener)
                opener.assert_not_called()
                with closing(store.connect()) as c:
                    self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0], 'PENDING')

    def test_historical_smtp_and_started_records_are_never_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, coordinator = self.setup_queue(Path(tmp)/'state.sqlite3')
            item = store.claim()
            store.finish(item['id'], 'SMTP_ACCEPTED')
            opener = Mock(return_value=self.response())
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'EMPTY')
            opener.assert_not_called()
            store.ingest('another', 'another-conflict', {'severity': 'RED'})
            store.claim()
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'BLOCKED_UNKNOWN')
            opener.assert_not_called()

    def test_operation_collision_and_post_ack_commit_failure_never_resend(self):
        for collision in (True, False):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as tmp:
                store, coordinator = self.setup_queue(Path(tmp)/'state.sqlite3')
                opener = Mock(return_value=self.response())
                if collision:
                    coordinator.begin_operation('notification:outbox:1', 'delivery', {})
                    self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'UNKNOWN')
                    opener.assert_not_called()
                else:
                    with patch.object(store, 'finish', side_effect=OSError('commit unavailable')):
                        with self.assertRaises(OSError):
                            send_one(store, coordinator, self.config(), opener=opener)
                    self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'BLOCKED_UNKNOWN')
                    self.assertEqual(opener.call_count, 1)

    def test_legacy_ack_and_explicit_test_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.sqlite3'
            store, coordinator = self.setup_queue(path)
            with closing(store.connect()) as c, c:
                p=json.loads(c.execute('SELECT payload FROM notification_outbox').fetchone()[0])
                p['test_only']=True
                c.execute('UPDATE notification_outbox SET payload=?', (json.dumps(p),))
            opener = Mock(return_value=self.response({'StatusCode': 0}))
            self.assertEqual(send_one(store, coordinator, self.config(), opener=opener), 'FEISHU_ACCEPTED')
            self.assertTrue(json.loads(opener.call_args.args[0].data)['content']['text'].startswith('【通道测试】'))

    def test_worker_is_unarmed_by_default_and_rejects_parallel_smtp(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(feishu_alert_watch.Path, 'home', return_value=home), \
                    patch.object(feishu_alert_watch, 'send_one') as sender:
                self.assertEqual(feishu_alert_watch.main(), 0)
                sender.assert_not_called()
                runtime=home/'.local/state/openclaw/runtime';runtime.mkdir(parents=True)
                (runtime/'FEISHU_ALERTS_ARMED').touch()
                (runtime/'EMAIL_ALERTS_ARMED').touch()
                with self.assertRaisesRegex(RuntimeError, 'SMTP'):
                    feishu_alert_watch.main()
                sender.assert_not_called()

    def test_default_http_opener_rejects_redirects(self):
        from reporting.incident_feishu import NoRedirect
        with self.assertRaises(RuntimeError):
            NoRedirect().redirect_request(None, None, 302, 'found', {}, 'https://example.invalid/')
