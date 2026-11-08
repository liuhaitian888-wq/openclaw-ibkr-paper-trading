from contextlib import closing
from datetime import datetime,timezone
import json,tempfile,unittest
from pathlib import Path
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.report_delivery_status import record_status,display

class ReportDeliveryStatusTests(unittest.TestCase):
    def setup_store(self,tmp,status='PENDING'):
        p=Path(tmp)/'recovery.sqlite3';RecoveryCoordinator(p);s=IncidentStore(p)
        with closing(s.connect()) as c,c:
            payload={'scheduled_at':1794013200,'queued_at':1794013200,'included_reports':['DAILY'],'missing_reports':[]}
            c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES('financial-reports:2026-11-07',1,'REPORT_BUNDLE',?,?)",(json.dumps(payload),status))
            return s,c.execute('SELECT id FROM notification_outbox').fetchone()[0]
    def test_same_evidence_is_recorded_once_after_restart_and_no_send_incident_created(self):
        now=datetime(2026,11,7,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            s,i=self.setup_store(tmp);self.assertEqual(record_status(s,now),1);self.assertEqual(record_status(IncidentStore(s.path),now),0)
            with closing(s.connect()) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM report_delivery_events').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM incidents').fetchone()[0],0)
                self.assertIn('REPORT_DELIVERY_STATUS',c.execute('SELECT payload FROM module_events').fetchone()[0])
    def test_unknown_survives_with_no_replay_then_native_receipt_is_separate_evidence(self):
        now=datetime(2026,11,7,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            s,i=self.setup_store(tmp,'UNKNOWN');record_status(s,now);self.assertIn('禁止自动重发',display(s,now))
            with closing(s.connect()) as c,c:
                c.execute("UPDATE notification_outbox SET status='TELEGRAM_ACCEPTED' WHERE id=?",(i,))
                c.execute('CREATE TABLE IF NOT EXISTS notification_receipts(notification_id INTEGER PRIMARY KEY,payload TEXT)')
                c.execute('INSERT INTO notification_receipts VALUES(?,?)',(i,json.dumps({'transport':'telegram','chat_id':-123,'message_ids':[94],'server_dates':['2026-11-07T01:00:02+00:00']})))
            self.assertEqual(record_status(s,now),1);text=display(s,now);self.assertIn('09:00:02 北京',text);self.assertIn('02:00:02 柏林',text)
            with closing(s.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM report_delivery_events').fetchone()[0],2)
    def test_acknowledged_missing_report_alert_is_not_report_delivery(self):
        now=datetime(2026,11,7,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            s,i=self.setup_store(tmp,'TELEGRAM_ACCEPTED')
            with closing(s.connect()) as c,c:
                c.execute('UPDATE notification_outbox SET payload=? WHERE id=?',(json.dumps({'included_reports':[],'missing_reports':['DAILY']}),i))
                c.execute('INSERT INTO notification_receipts VALUES(?,?)',(i,json.dumps({'transport':'telegram','chat_id':-123,'message_ids':[156],'server_dates':['2026-11-07T01:00:02+00:00']})))
            record_status(s,now)
            self.assertIn('仅缺报告警，未附今日日报',display(s,now))
            with closing(s.connect()) as c:d=json.loads(c.execute('SELECT payload FROM report_delivery_status').fetchone()[0])
            self.assertTrue(d['telegram_server_accepted']);self.assertFalse(d['daily_report_server_accepted'])

    def test_status_without_native_receipt_is_not_verified_success(self):
        now=datetime(2026,11,7,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            s,i=self.setup_store(tmp,'TELEGRAM_ACCEPTED');record_status(s,now)
            self.assertIn('原生回执待核验',display(s,now))
            with closing(s.connect()) as c:self.assertFalse(json.loads(c.execute('SELECT payload FROM report_delivery_status').fetchone()[0])['telegram_server_accepted'])

    def test_corrupt_report_evidence_is_logged_without_blocking_other_delivery_or_replaying(self):
        now=datetime(2026,11,7,13,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            s,i=self.setup_store(tmp,'UNKNOWN')
            with closing(s.connect()) as c,c:c.execute("UPDATE notification_outbox SET payload='invalid' WHERE id=?",(i,))
            self.assertEqual(record_status(s,now),1)
            with closing(s.connect()) as c:
                d=json.loads(c.execute('SELECT payload FROM report_delivery_status').fetchone()[0]);self.assertEqual(d['status'],'EVIDENCE_INVALID')
                self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0],'UNKNOWN')
