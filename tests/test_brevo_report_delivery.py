from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.report_schedule import BJ, enqueue_reports
from reporting.incident_mail import send_one


class BrevoReportTests(unittest.TestCase):
    def prepare(self, root):
        now = datetime(2026, 11, 5, 9, tzinfo=BJ)
        directory = root / now.date().isoformat()
        directory.mkdir()
        png = directory / 'DAILY.png'
        png.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        report = dict(generated_at=now.isoformat(), source_snapshot_at=now.isoformat(),
                      report_date=now.date().isoformat(), report_type='DAILY', account_id='DU123',
                      environment='PAPER', source_validated=True, image_path=str(png),
                      image_sha256=hashlib.sha256(png.read_bytes()).hexdigest(),
                      trading_period=dict(start_date='2026-11-04',end_date_exclusive='2026-11-05'))
        (directory/'DAILY.json').write_text(json.dumps(report))
        co=RecoveryCoordinator(root/'recovery.sqlite3');store=IncidentStore(co.path)
        self.assertEqual(enqueue_reports(store,root,'DU123',now,transport='smtp'),'REPORT_BUNDLE')
        return store,co,png,now

    def test_local_png_without_feishu_token_is_attached_and_ack_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,co,png,now=self.prepare(root)
            client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
            client.send_message.return_value={};factory=Mock(return_value=client)
            cfg=dict(host='relay.invalid',sender='test@example.invalid',username='fixture',relay_password='fixture')
            self.assertEqual(send_one(store,co,cfg,report_root=root,smtp_factory=factory,clock=lambda:100),'SMTP_ACCEPTED')
            message=client.send_message.call_args.args[0]
            self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True),png.read_bytes())
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT status,ack_received_at FROM notification_delivery').fetchone(),('SMTP_ACCEPTED',100))
            self.assertEqual(send_one(store,co,cfg,report_root=root,smtp_factory=factory),'EMPTY')
            factory.assert_called_once()

    def test_tamper_or_path_escape_never_reaches_smtp_and_unknown_is_held(self):
        for escape in (False,True):
            with self.subTest(escape=escape),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);store,co,png,now=self.prepare(root)
                if not escape:png.write_bytes(b'changed')
                factory=Mock();cfg=dict(host='relay.invalid',sender='test@example.invalid',username='fixture',relay_password='fixture')
                with self.assertRaises(ValueError):
                    send_one(store,co,cfg,report_root=root/'other' if escape else root,smtp_factory=factory)
                factory.assert_not_called()
                self.assertEqual(send_one(IncidentStore(co.path),co,cfg,smtp_factory=factory),'BLOCKED_UNKNOWN')

    def test_default_feishu_schedule_rejects_png_without_image_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,co,png,now=self.prepare(root)
            from reporting.report_schedule import ready_reports
            ready,missing=ready_reports(root,now.date(),'DU123',now)
            self.assertFalse(ready);self.assertIn('DAILY',missing)

    def test_builder_binds_local_png_and_transport_change_requires_render(self):
        from reporting.financial_reports import prepare_reports
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            now=datetime(2026,11,5,9,tzinfo=BJ)
            (root/'runtime/paper-observer.latest.json').write_text(json.dumps(dict(
                source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',
                observed_at=now.isoformat(),positions=[],account={})))
            prepare_reports(root,'DU123',now,publish_image=lambda *_:'img_fixture')
            renderer=Mock(side_effect=lambda html,png: (png.write_bytes(b'\x89PNG\r\n\x1a\nfixture'),None)[1])
            result=prepare_reports(root,'DU123',now,publish_image=renderer,transport='smtp')
            renderer.assert_called_once()
            report=json.loads((Path(result['directory'])/'DAILY.json').read_text())
            self.assertEqual(report['image_sha256'],hashlib.sha256(Path(report['image_path']).read_bytes()).hexdigest())
            prepare_reports(root,'DU123',now,publish_image=renderer,transport='smtp')
            renderer.assert_called_once()
