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
