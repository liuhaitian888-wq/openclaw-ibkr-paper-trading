from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reporting import capacity as cap
from reporting.incidents import IncidentStore


def sample(at=0, available=12*cap.GIB, rows=10, failures=0):
    dbs = {row[0]: dict(state='OBSERVED', identity=[1, i], bytes=4096,
        wal_bytes=0, shm_bytes=0, rows={'fixture': rows}) for i, row in enumerate(cap.DATABASES)}
    dbs['runtime/recovery.sqlite3']['notification_error_events'] = failures
    return dict(at=at, filesystem=[1, 1000, 4096], total_bytes=40*cap.GIB,
        available_bytes=available, free_fraction=available/(40*cap.GIB), databases=dbs)


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'runtime').mkdir()
        self.store = IncidentStore(self.root/'runtime/recovery.sqlite3', clock=lambda: 1000)

    def snapshot(self, now):
        return cap.read(self.root, now=now)

    def outbox(self):
        with closing(self.store.connect()) as c:
            return c.execute('SELECT kind,payload FROM notification_outbox ORDER BY id').fetchall()

    def run_tick(self, value):
        with patch.object(cap, 'collect_sample', return_value=value), patch.object(cap, 'tree_inventory', return_value={'complete': True}):
            return cap.tick(self.root, now=value['at'])

    def test_real_read_only_metadata_and_bounded_fixed_counts(self):
        path = self.root/'trading_audit.sqlite3'
        with closing(sqlite3.connect(path)) as c, c:
            c.execute('CREATE TABLE paper_readback_observations(id INTEGER)')
            c.executemany('INSERT INTO paper_readback_observations VALUES(?)', [(1,), (2,)])
        before = path.read_bytes()
        value = cap.database_sample(self.root, 'trading_audit.sqlite3')
        self.assertEqual(value['state'], 'OBSERVED')
        self.assertEqual(value['rows']['paper_readback_observations'], 2)
        self.assertGreater(value['page_count'], 0)
        self.assertEqual(path.read_bytes(), before)
        missing = cap.database_sample(self.root, 'financial_ledger.sqlite3')
        self.assertEqual(missing['state'], 'MISSING')
        self.assertFalse((self.root/'financial_ledger.sqlite3').exists())
        (self.root/'financial_ledger.sqlite3').symlink_to(path)
        self.assertEqual(cap.database_sample(self.root, 'financial_ledger.sqlite3')['state'], 'UNAVAILABLE')

    def test_counts_unavailable_are_unknown_not_zero(self):
        value = cap.database_sample(self.root, 'runtime/recovery.sqlite3')
        self.assertIsNone(value['rows']['paper_callback_events'])
        self.assertEqual(value['notification_error_events'], 0)
        with closing(sqlite3.connect(self.store.path)) as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            self.assertEqual(cap.database_sample(self.root, 'runtime/recovery.sqlite3')['state'], 'UNAVAILABLE')

    def test_budget_aborts_pathological_count_and_auxiliary_metadata_is_separate(self):
        path = self.root/'trading_audit.sqlite3'
        with closing(sqlite3.connect(path)) as c, c:
            c.execute('CREATE VIEW paper_readback_observations AS WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT x FROM n')
        value = cap.database_sample(self.root, 'trading_audit.sqlite3')
        self.assertIsNone(value['rows']['paper_readback_observations'])
        oauth = self.root/'secretary-oauth'
        oauth.mkdir()
        with closing(sqlite3.connect(oauth/'logs_2.sqlite')) as c:
            c.execute('CREATE TABLE internal_private(payload TEXT)')
        with patch.object(cap.sqlite3,'connect',side_effect=AssertionError('internal DB must remain stat-only')):
            internal=cap.database_sample(self.root, 'secretary-oauth/logs_2.sqlite')
        self.assertEqual(internal['rows'], {})
        self.assertEqual(internal['state'],'STAT_ONLY_INTERNAL')
        from reporting.secretary_read import REGISTRY
        self.assertNotIn('secretary-oauth/logs_2.sqlite', REGISTRY)
        (self.root/'new-runtime.db').write_text('fixture')
        found = cap.tree_inventory(self.root)
        self.assertIn('new-runtime.db', [row['path'] for row in found['unregistered_sqlite']])

    def test_sparse_discontinuous_identity_and_nonpositive_growth(self):
        self.assertEqual(cap.growth([sample()])['state'], 'UNKNOWN')
        self.assertEqual(cap.growth([sample(0), sample(1800), sample(3600)])['state'], 'UNKNOWN')
        rows = [sample(t, 12*cap.GIB-t*1024) for t in range(0, 3900, 300)]
        rates = cap.growth(rows)
        self.assertEqual(rates['state'], 'OBSERVED')
        self.assertAlmostEqual(rates['filesystem_bytes_day'], 1024*86400)
        self.assertGreater(rates['days_to_full'], 0)
        rows[-1]['databases']['trading_audit.sqlite3']['identity'] = [1, 999]
        self.assertNotIn('trading_audit.sqlite3', cap.growth(rows)['database_bytes_day'])
        for row in rows:
            row['available_bytes'] = 12*cap.GIB
        self.assertIsNone(cap.growth(rows)['days_to_full'])
        rows[-1]['filesystem'] = [2, 1000, 4096]
        self.assertEqual(cap.growth(rows)['state'], 'UNKNOWN')

    def test_row_error_and_byte_growth_have_independent_thresholds(self):
        rows = [sample(t, rows=10+2*t, failures=t//30) for t in range(0, 3900, 300)]
        rows[-1]['databases']['agent_secretary.sqlite3']['bytes'] = cap.GIB
        risk = cap.assess(rows, {})
        self.assertEqual(risk['state'], 'CRITICAL')
        self.assertIn('ROW_GROWTH_WARNING', risk['reasons'])
        self.assertIn('NOTIFICATION_ERROR_EVENT_GROWTH_CRITICAL', risk['reasons'])
        self.assertIn('DB_GROWTH_CRITICAL', risk['reasons'])

    def test_warning_critical_dedup_restart_and_stable_recovery(self):
        self.run_tick(sample(0, 7*cap.GIB))
        self.run_tick(sample(300, 7*cap.GIB))
        self.assertEqual(len(self.outbox()), 0)
        self.assertFalse(self.run_tick(sample(301, cap.GIB)))
        self.run_tick(sample(600, cap.GIB))
        self.assertEqual([row[0] for row in self.outbox()], ['ALERT'])
        # A discontinuity resets growth; 3 good samples are still mandatory.
        for t in (3000, 3300):
            self.run_tick(sample(t, 15*cap.GIB))
            self.assertNotIn('RECOVERY', [r[0] for r in self.outbox()])
        self.run_tick(sample(3600, 15*cap.GIB))
        self.assertEqual([r[0] for r in self.outbox()], ['ALERT'])
        self.assertEqual(self.snapshot(3601)['state'], 'OK')
        self.assertEqual(self.snapshot(5000)['state'], 'STALE')

    def test_snapshot_then_outbox_crash_reconciles_without_replay(self):
        with patch.object(cap, '_publish', side_effect=RuntimeError('fixture crash')):
            with self.assertRaises(RuntimeError):
                self.run_tick(sample(0, cap.GIB))
        self.assertEqual(len(self.outbox()), 0)
        self.run_tick(sample(1, cap.GIB))
        self.assertEqual(len(self.outbox()), 1)
        self.run_tick(sample(2, cap.GIB))
        self.assertEqual(len(self.outbox()), 1)

    def test_ring_and_tree_are_bounded_and_reads_never_probe(self):
        for t in range(0, (cap.MAX_SAMPLES+3)*300, 300):
            self.run_tick(sample(t))
        raw = (self.root/'runtime/capacity.json').read_bytes()
        self.assertLess(len(raw), cap.MAX_BYTES)
        self.assertEqual(self.snapshot(t)['sample_count'], cap.MAX_SAMPLES)
        with patch.object(cap, 'collect_sample', side_effect=AssertionError('read must not collect')):
            from reporting.secretary_read import tool
            self.assertEqual(tool(self.root, {'name': 'capacity'})['sample_count'], cap.MAX_SAMPLES)
        for n in range(5):
            (self.root/f'fixture-{n}.db').write_text('fixture')
        (self.root/'outside').symlink_to('/tmp')
        self.assertFalse(cap.tree_inventory(self.root, max_entries=1)['complete'])
        self.assertTrue(cap.tree_inventory(self.root)['complete'])

    def test_wal_persistent_and_unknown_probe_growth(self):
        rows = [sample(t) for t in (0, 300, 600)]
        for row in rows:
            row['databases']['trading_audit.sqlite3']['wal_bytes'] = 70*1024**2
        self.assertIn('WAL_PERSISTENT', cap.assess(rows, {})['reasons'])
        rows[-1]['databases']['trading_audit.sqlite3']['wal_bytes'] = cap.GIB
        self.assertEqual(cap.assess(rows, {})['state'], 'CRITICAL')
        for row in rows:
            row['databases']['financial_ledger.sqlite3']['state'] = 'UNAVAILABLE'
        self.assertIn('METADATA_REPEATED_UNAVAILABLE', cap.assess(rows, {})['reasons'])

    def test_public_view_uses_only_validated_numeric_fields(self):
        self.run_tick(sample(0, cap.GIB))
        item = dict(incident_key='storage-capacity', kind='ALERT', payload=json.loads(self.outbox()[0][1]))
        item['payload']['reason'] = 'private fixture account DU1234567 api_key'
        text = cap.public_status(item)
        self.assertIn('1.00 GiB', text)
        self.assertNotIn('fixture', text)
        self.assertNotIn('DU1234567', text)
        invalid = deepcopy(item)
        invalid['payload']['capacity']['days_to_full'] = float('nan')
        self.assertIsNone(cap.public_status(invalid))
        invalid = deepcopy(item)
        invalid['payload']['capacity']['available_bytes'] = True
        self.assertIsNone(cap.public_status(invalid))
        invalid = deepcopy(item)
        invalid['payload']['capacity']['free_text'] = 'private'
        self.assertIsNone(cap.public_status(invalid))

    def test_new_policy_archives_ordinary_and_critical_is_owner_only(self):
        self.run_tick(sample(0, 7*cap.GIB))
        self.assertEqual(self.outbox(), [])
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM incident_events WHERE incident_key='storage-capacity'").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM incidents WHERE incident_key='storage-capacity' AND state='OPEN'").fetchone()[0], 0)
        self.run_tick(sample(300, cap.GIB))
        payload = json.loads(self.outbox()[0][1])
        from reporting.notification_access import decision
        item = dict(incident_key='storage-capacity', kind='ALERT', payload=payload)
        self.assertEqual(decision(item, {'automatic_updates_to_group': True})['audience'], 'owner')
        self.assertTrue(payload['requires_response'])
        self.assertTrue(payload['private_notice'])

    def test_registry_is_optional_and_stale_never_healthy(self):
        from datetime import datetime, timezone
        from reporting.health import resolve_modules
        now = datetime.fromtimestamp(2000, timezone.utc)
        self.assertFalse(resolve_modules({}, now=now)['CAPACITY']['active'])
        result = resolve_modules({'CAPACITY': dict(enabled=True, state='HEALTHY', freshness='FRESH',
            observed_at=datetime.fromtimestamp(0, timezone.utc).isoformat())}, now=now)
        self.assertEqual(result['CAPACITY']['freshness'], 'STALE')
        self.assertEqual(result['CAPACITY']['state'], 'DEGRADED')
