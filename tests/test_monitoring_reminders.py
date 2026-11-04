from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest

from reporting.incidents import IncidentStore


class ReminderTests(unittest.TestCase):
    def test_rollout_summary_survives_restart_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.sqlite3';store=IncidentStore(path)
            store.ingest('first','gateway',{'severity':'RED'})
            self.assertTrue(store.enqueue_current_summary('release-1'))
            self.assertFalse(IncidentStore(path).enqueue_current_summary('release-1'))
    def test_latest_stage_restart_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000000.0]
            path = Path(tmp) / 'state.sqlite3'
            store = IncidentStore(path, clock=lambda: now[0])
            store.ingest('first', 'gateway', {'severity': 'RED', 'reason': 'API closed'})
            initial = store.claim()
            store.finish(initial['id'], 'FEISHU_ACCEPTED')
            self.assertEqual(store.enqueue_due_reminders(), 0)
            now[0] += 1800
            self.assertEqual(store.enqueue_due_reminders(), 1)
            self.assertEqual(store.enqueue_due_reminders(), 0)
            item = store.claim()
            self.assertEqual(item['kind'], 'REMINDER_1')
            store.finish(item['id'], 'FEISHU_ACCEPTED')
            now[0] += 3 * 86400
            store = IncidentStore(path, clock=lambda: now[0])
            self.assertEqual(store.enqueue_due_reminders(), 1)
            item = store.claim()
            self.assertEqual(item['kind'], 'REMINDER_5')
            self.assertEqual(item['payload']['reminder_stage'], 5)
            store.finish(item['id'], 'FEISHU_ACCEPTED')
            self.assertEqual(store.enqueue_due_reminders(), 0)
            store.ingest('resolved', 'gateway', {'severity': 'GREEN'}, resolved=True)
            now[0] += 86400
            self.assertEqual(store.enqueue_due_reminders(), 0)

    def test_uncertain_initial_is_not_bypassed_and_new_occurrence_rearms(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000000.0]
            store = IncidentStore(Path(tmp) / 'state.sqlite3', clock=lambda: now[0])
            store.ingest('first', 'gateway', {'severity': 'RED'})
            item = store.claim()
            store.finish(item['id'], 'UNKNOWN')
            now[0] += 172800
            self.assertEqual(store.enqueue_due_reminders(), 0)
            self.assertTrue(store.uncertain_notifications())

    def test_two_hour_boundary_and_delivery_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000000.0]
            store = IncidentStore(Path(tmp) / 'state.sqlite3', clock=lambda: now[0])
            store.ingest('first', 'gateway', {'severity': 'RED'})
            item = store.claim()
            store.delivery_started(item['id'], now[0])
            store.delivery_finished(item['id'], 'FEISHU_ACCEPTED', ack_at=now[0] + 2)
            store.finish(item['id'], 'FEISHU_ACCEPTED')
            now[0] += 7200
            self.assertEqual(store.enqueue_due_reminders(), 1)
            self.assertEqual(store.claim()['kind'], 'REMINDER_2')
            with closing(store.connect()) as c:
                evidence = c.execute('SELECT attempt_started_at,ack_received_at,provider_created_at '
                                     'FROM notification_delivery').fetchone()
            self.assertEqual(evidence, (1000000, 1000002, None))
