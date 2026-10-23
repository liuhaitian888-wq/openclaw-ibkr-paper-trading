from contextlib import closing, nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from reporting.incidents import IncidentStore
from reporting.incident_mail import send_one, RECIPIENT
from reporting.recovery import RecoveryCoordinator
from ops.cloud import alert_email


class MailTests(unittest.TestCase):
    def setup_queue(self, path):
        coordinator = RecoveryCoordinator(path)
        store = IncidentStore(path, clock=lambda: 1792764000)
        store.ingest('fault1', 'order1', dict(severity='RED', symbol='AAPL', order_type='STP',
            ib_error_code=201, reason='protective order rejected', scope='SYMBOL', action_taken='report_only',
            user_action='reconcile', recovery_condition='verified coverage', timestamp='2026-10-23T12:00:00+00:00'))
        return store, coordinator

    def smtp(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.send_message.return_value = {}
        return client

    def cfg(self):
        return dict(host='relay.invalid', sender='paper@example.invalid', username='fixture', relay_password='fixture')

    def test_acceptance_recovery_order_duration_and_fixed_recipient(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, coordinator = self.setup_queue(Path(tmp) / 'recovery.sqlite3')
            store.clock = lambda: 1792764012
            store.ingest('restored', 'order1', dict(severity='GREEN', scope='SYMBOL', reason='verified coverage'), resolved=True)
            smtp = self.smtp()
            factory = Mock(return_value=smtp)
            self.assertEqual(send_one(store, coordinator, self.cfg(), trading_status='PAUSED', smtp_factory=factory), 'SMTP_ACCEPTED')
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message['To'], RECIPIENT)
            self.assertEqual(smtp.send_message.call_args.kwargs['to_addrs'], [RECIPIENT])
            self.assertIn('Europe/Berlin', message.get_content())
            self.assertIn('PAUSED', message.get_content())
            self.assertIn('201', message.get_content())
            self.assertNotIn('fixture', message.get_content())
            self.assertEqual(send_one(store, coordinator, self.cfg(), smtp_factory=factory), 'SMTP_ACCEPTED')
            self.assertIn('12', smtp.send_message.call_args.args[0].get_content())
            self.assertEqual(send_one(store, coordinator, self.cfg(), smtp_factory=factory), 'EMPTY')
            self.assertEqual(factory.call_count, 2)
            with closing(store.connect()) as c:
                self.assertEqual(c.execute("SELECT DISTINCT status FROM operation_attempts").fetchall(), [('SENT_ACCEPTED',)])

    def test_ambiguous_send_blocks_recovery_and_never_replays_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.sqlite3'
            store, coordinator = self.setup_queue(path)
            store.ingest('recovered', 'order1', {'severity': 'GREEN'}, resolved=True)
            smtp = self.smtp()
            smtp.send_message.side_effect = ConnectionError('ACK lost')
            factory = Mock(return_value=smtp)
            with self.assertRaises(ConnectionError):
                send_one(store, coordinator, self.cfg(), smtp_factory=factory)
            self.assertEqual(send_one(IncidentStore(path), RecoveryCoordinator(path), self.cfg(), smtp_factory=factory), 'BLOCKED_UNKNOWN')
            factory.assert_called_once()
            self.assertEqual(coordinator.uncertainties(), [('notification:outbox:1', 'delivery', 'UNKNOWN')])
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT status FROM notification_outbox ORDER BY id').fetchall(), [('UNKNOWN',), ('PENDING',)])

    def test_tls_auth_refusal_quit_and_process_crash_keep_uncertainty(self):
        for failure in ('starttls', 'login', 'refusal', 'quit', 'crash'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                store, coordinator = self.setup_queue(Path(tmp) / 'recovery.sqlite3')
                smtp = self.smtp()
                if failure == 'refusal':
                    smtp.send_message.return_value = {RECIPIENT: (550, b'refused')}
                elif failure == 'quit':
                    smtp.__exit__.side_effect = ConnectionError('QUIT failed after DATA')
                elif failure == 'crash':
                    smtp.send_message.side_effect = KeyboardInterrupt()
                else:
                    getattr(smtp, failure).side_effect = ConnectionError('transport failure')
                factory = Mock(return_value=smtp)
                with self.assertRaises(BaseException):
                    send_one(store, coordinator, self.cfg(), smtp_factory=factory)
                self.assertEqual(send_one(store, coordinator, self.cfg(), smtp_factory=factory), 'BLOCKED_UNKNOWN')
                factory.assert_called_once()

    def test_reserved_or_legacy_operation_is_not_sent_again(self):
        for reserve in ('outbox', 'operation'):
            with self.subTest(reserve=reserve), tempfile.TemporaryDirectory() as tmp:
                store, coordinator = self.setup_queue(Path(tmp) / 'recovery.sqlite3')
                if reserve == 'outbox':
                    store.claim()
                else:
                    coordinator.begin_operation('notification:outbox:1', 'delivery', {})
                factory = Mock()
                send_one(store, coordinator, self.cfg(), smtp_factory=factory)
                factory.assert_not_called()

    def test_disabled_entry_never_reads_configuration_or_opens_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, 'home', return_value=Path(tmp)), patch.object(alert_email.smtplib, 'SMTP') as smtp, redirect_stdout(io.StringIO()):
                self.assertEqual(alert_email.main(), 0)
                smtp.assert_not_called()

    def test_commit_failure_after_smtp_acceptance_cannot_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, coordinator = self.setup_queue(Path(tmp)/'recovery.sqlite3')
            factory=Mock(return_value=self.smtp())
            with patch.object(store,'finish',side_effect=OSError('commit unavailable')):
                with self.assertRaises(OSError):
                    send_one(store,coordinator,self.cfg(),smtp_factory=factory)
            self.assertEqual(send_one(store,coordinator,self.cfg(),smtp_factory=factory),'BLOCKED_UNKNOWN')
            factory.assert_called_once()
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0],'STARTED')
                self.assertEqual(c.execute('SELECT status FROM operation_attempts').fetchone()[0],'SENT_ACCEPTED')
