from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.recovery import RecoveryCoordinator


class SourceTests(unittest.TestCase):
    def test_baseline_partial_record_restart_and_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.jsonl'
            path.write_text('historical payload not replayed\n')
            store = IncidentStore(Path(tmp) / 'state.sqlite3')
            collector = IncidentCollector(store)
            self.assertEqual(collector.rejections(path), 0)
            row = json.dumps(dict(timestamp='2026-10-23T14:00:00+00:00', local_plan_id='order1', symbol='AAPL'))
            with path.open('a') as f:
                f.write(row)
            self.assertEqual(collector.rejections(path), 0)
            with path.open('a') as f:
                f.write('\n')
            self.assertEqual(IncidentCollector(store).rejections(path), 1)
            self.assertEqual(collector.rejections(path), 0)
            self.assertEqual(store.claim()['payload']['scope'], 'ORDER')
            path.rename(path.with_suffix('.old'))
            path.write_text(row + '\n')
            with self.assertRaises(EvidenceChanged):
                collector.rejections(path)

    def test_bad_batch_rolls_back_event_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.jsonl'
            store = IncidentStore(Path(tmp) / 'state.sqlite3')
            collector = IncidentCollector(store)
            collector.rejections(path)  # Missing at baseline: new file starts at zero.
            row = json.dumps(dict(timestamp='now', local_plan_id='o')) + '\n'
            path.write_text(row + 'bad-json\n')
            with self.assertRaises(ValueError):
                collector.rejections(path)
            self.assertIsNone(store.claim())
            path.write_text(row)
            self.assertEqual(collector.rejections(path), 1)

    def test_coordinator_fresh_recovery_and_no_historical_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.sqlite3'
            now = datetime.now(timezone.utc).timestamp()
            coordinator = RecoveryCoordinator(path, clock=lambda: now)
            coordinator.observe('DIAGNOSTICS', 'FAILED')
            store = IncidentStore(path, clock=lambda: now)
            collector = IncidentCollector(store)
            self.assertEqual(collector.module_events(), 0)
            self.assertIsNone(store.claim())
            coordinator.observe('DIAGNOSTICS', 'FAILED', reason='new failure')
            collector.module_events()
            alert = store.claim()
            self.assertEqual(alert['kind'], 'ALERT')
            store.finish(alert['id'], 'SMTP_ACCEPTED')
            coordinator.observe('DIAGNOSTICS', 'HEALTHY', freshness='STALE')
            collector.module_events()
            self.assertIsNone(store.claim())
            coordinator.observe('DIAGNOSTICS', 'HEALTHY', freshness='FRESH')
            collector.module_events()
            self.assertEqual(store.claim()['kind'], 'RECOVERY')
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM incident_events').fetchone()[0], 2)

    def test_unknown_transition_is_alerted_once_and_never_auto_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'recovery.sqlite3'
            coordinator = RecoveryCoordinator(path)
            coordinator.begin_operation('historical', 'order', {})
            coordinator.finish_operation('historical', 'UNKNOWN')
            store = IncidentStore(path)
            collector = IncidentCollector(store)
            self.assertEqual(collector.unknown_operations(), 0)
            self.assertIsNone(store.claim())
            coordinator.finish_operation('historical', 'CONFIRMED')
            collector.unknown_operations()
            self.assertTrue(coordinator.begin_operation('new', 'order', {}))
            collector.unknown_operations()
            coordinator.finish_operation('new', 'UNKNOWN')
            self.assertEqual(collector.unknown_operations(), 1)
            alert = store.claim()
            self.assertEqual(alert['payload']['severity'], 'RED')
            store.finish(alert['id'], 'SMTP_ACCEPTED')
            self.assertEqual(collector.unknown_operations(), 0)
            coordinator.finish_operation('new', 'CONFIRMED')
            collector.unknown_operations()
            self.assertIsNone(store.claim())
