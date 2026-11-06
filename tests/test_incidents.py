import tempfile
from pathlib import Path
import unittest
from reporting.incidents import IncidentStore


class IncidentTests(unittest.TestCase):
    def test_restart_dedup_resolution_and_recurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.sqlite3'
            s = IncidentStore(path)
            self.assertTrue(s.ingest('e1', 'order:1', {'reason': 'rejected'}))
            self.assertFalse(s.ingest('e1', 'order:1', {'reason': 'rejected'}))
            s.ingest('e2', 'order:1', {'reason': 'again'})
            s.ingest('e3', 'order:1', {'proof': 'explicit'}, resolved=True)
            alert = s.claim()
            self.assertEqual(alert['kind'], 'ALERT')
            self.assertIsNone(IncidentStore(path).claim())
            s.finish(alert['id'], 'SMTP_ACCEPTED')
            recovery = s.claim()
            self.assertEqual(recovery['kind'], 'RECOVERY')
            s.finish(recovery['id'], 'SMTP_ACCEPTED')
            s.ingest('e4', 'order:1', {'reason': 'new occurrence'})
            self.assertEqual(s.claim()['kind'], 'ALERT')

    def test_unknown_blocks_only_affected_incident(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = IncidentStore(Path(tmp) / 'state.sqlite3')
            s.ingest('a', 'a', {})
            first = s.claim()
            s.finish(first['id'], 'UNKNOWN')
            s.ingest('ar', 'a', {}, resolved=True)
            self.assertIsNone(s.claim())
            s.ingest('b', 'b', {})
            self.assertEqual(s.claim()['kind'], 'ALERT')
            with self.assertRaises(ValueError):
                s.ingest('a', 'b', {})
            with self.assertRaises(ValueError):
                s.finish(first['id'], 'SMTP_ACCEPTED')

    def test_concurrent_claim_is_unique(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.sqlite3'
            s = IncidentStore(path)
            s.ingest('a', 'a', {})
            stores = [IncidentStore(path), IncidentStore(path)]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda item: item.claim(), stores))
            self.assertEqual(sum(item is not None for item in results), 1)

    def test_severity_escalation_is_not_hidden_by_incident_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'state.sqlite3')
            store.ingest('e1','paper',{'severity':'YELLOW'})
            first=store.claim(); store.finish(first['id'],'SMTP_ACCEPTED')
            store.ingest('e2','paper',{'severity':'RED'})
            escalation=store.claim()
            self.assertEqual(escalation['kind'],'ESCALATION_RED')
            store.finish(escalation['id'],'SMTP_ACCEPTED')
            store.ingest('e3','paper',{'severity':'RED'})
            self.assertIsNone(store.claim())

    def test_one_shot_channel_tests_never_create_recurring_reminders(self):
        from contextlib import closing
        now=[1000]
        with tempfile.TemporaryDirectory() as tmp:
            s=IncidentStore(Path(tmp)/'state.sqlite3',clock=lambda:now[0])
            s.ingest('test-event','old-channel-test',dict(scope='NOTIFICATION_CHANNEL_TEST',reason='one authorized test'))
            first=s.claim();s.finish(first['id'],'TELEGRAM_ACCEPTED')
            s.ingest('real-event','real-fault',dict(scope='PAPER_SAFETY',reason='connection lost'))
            first=s.claim();s.finish(first['id'],'TELEGRAM_ACCEPTED')
            now[0]+=90000
            self.assertEqual(s.enqueue_due_reminders(),1)
            with closing(s.connect()) as c:
                self.assertEqual(c.execute("select count(*) from notification_outbox where incident_key='old-channel-test'").fetchone()[0],1)
            self.assertEqual(s.claim()['incident_key'],'real-fault')
