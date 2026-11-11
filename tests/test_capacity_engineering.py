from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reporting import capacity, capacity_engineering as follow
from reporting.agent_secretary import SecretaryArchive
from reporting.engineering_tasks import initialize
from reporting.incidents import IncidentStore


class CapacityEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root/'runtime').mkdir()
        self.archive = SecretaryArchive(self.root/'agent_secretary.sqlite3', clock=lambda: 1000)
        initialize(self.archive)
        self.store = IncidentStore(self.root/'runtime/recovery.sqlite3', clock=lambda: 1000)

    def event(self, level):
        data = {'version': 1, 'samples': [{'at': 1000, 'total_bytes': 40*capacity.GIB,
            'available_bytes': capacity.GIB}], 'risk': {'level': level,
            'state': ('OK','WARNING','CRITICAL')[level], 'growth': {'days_to_full': 1.5}}, 'inventory': {}}
        capacity._publish(self.root, data); capacity._save(self.root, data)

    def tasks(self):
        return follow.read(self.root)['items']

    def test_historical_severe_after_recovery_is_one_system_task_without_new_outbox(self):
        self.event(1); self.event(2); self.event(0)
        self.assertEqual(follow.reconcile(self.root)['state'], 'CURRENT')
        for _ in range(3): follow.reconcile(self.root)
        item, = self.tasks()
        self.assertEqual(item['id'], 'capacity-followup:2')
        self.assertEqual(item['state'], 'QUEUED_READ_ONLY')
        self.assertEqual(item['source_event'], 'storage-capacity:2')
        self.assertFalse(item['grants_model_execution']); self.assertFalse(item['desktop_chat_wakeup_connected'])
        with closing(self.archive.connect()) as c:
            self.assertEqual(c.execute("SELECT origin,kind FROM secretary_events WHERE occurrence=?", (item['id'],)).fetchone(), ('SYSTEM','ENGINEERING_PROPOSAL'))
            self.assertEqual(c.execute('SELECT count(*) FROM secretary_runs').fetchone()[0], 0)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0], 1)

    def test_destination_commit_then_cursor_failure_is_reconciled_without_replay(self):
        self.event(2)
        with patch.object(follow, '_save', side_effect=OSError('fixture crash')):
            self.assertEqual(follow.reconcile(self.root)['state'], 'BLOCKED')
        self.assertEqual(len(self.tasks()), 1)

        self.assertEqual(follow.reconcile(self.root)['state'], 'CURRENT')
        self.assertEqual(len(self.tasks()), 1)

    def test_warning_critical_flap_reuses_episode_but_new_recovered_episode_is_distinct(self):
        self.event(2); follow.reconcile(self.root)
        self.event(1); follow.reconcile(self.root)
        self.event(2); follow.reconcile(self.root)
        self.assertEqual([x['id'] for x in self.tasks()],['capacity-followup:1'])
        self.event(0); follow.reconcile(self.root)
        self.event(2); follow.reconcile(self.root)
        self.assertEqual({x['id'] for x in self.tasks()},{'capacity-followup:1','capacity-followup:5'})
        self.assertEqual(follow.reconcile(self.root)['state'], 'CURRENT')
        self.assertEqual(len(self.tasks()), 2)

    def test_claim_revalidates_source_fingerprint_and_unknown_is_never_reclaimed(self):
        self.event(2); follow.reconcile(self.root); item, = self.tasks()
        with self.assertRaises(ValueError): follow.claim(self.root, item['id'], '0'*64, 'codex-host')
        started = follow.claim(self.root, item['id'], item['payload_sha256'], 'codex-host')
        self.assertEqual(started['state'], 'STARTED_READ_ONLY')
        self.assertEqual(follow.claim(self.root, item['id'], item['payload_sha256'], 'codex-host')['state'], 'NOT_CLAIMED')
        with self.assertRaises(PermissionError): follow.finish(self.root, item['id'], 'other', 'UNKNOWN', 'No result')
        follow.finish(self.root, item['id'], 'codex-host', 'UNKNOWN', 'Outcome needs reconciliation')
        self.event(0); follow.reconcile(self.root)
        self.assertEqual(self.tasks()[0]['state'], 'UNKNOWN')
        self.assertEqual(follow.claim(self.root, item['id'], item['payload_sha256'], 'other')['state'], 'NOT_CLAIMED')
        with self.assertRaises(ValueError): follow.claim(self.root, 'engineering-development:original', item['payload_sha256'], 'codex-host')

    def test_changed_source_or_unpaired_event_blocks_without_overwriting_task(self):
        self.event(2); follow.reconcile(self.root); item, = self.tasks()
        with closing(self.store.connect()) as c, c:
            c.execute("UPDATE incident_events SET payload='{}' WHERE event_id='storage-capacity:1'")
        with self.assertRaises(ValueError): follow.claim(self.root, item['id'], item['payload_sha256'], 'codex-host')
        self.assertEqual(self.tasks()[0]['state'], 'QUEUED_READ_ONLY')

    def test_batch_and_task_bounds_preserve_source_backlog(self):
        for n in range(11): self.event(1 if n%2 == 0 else 0)
        first = follow.reconcile(self.root)
        self.assertEqual(first['through_sequence'], 8); self.assertEqual(first['state'], 'BACKLOG')
        self.assertEqual(follow.reconcile(self.root)['through_sequence'], 11)
        with closing(self.archive.connect()) as c, c:
            for n in range(128):
                c.execute("INSERT INTO secretary_engineering_tasks VALUES (?,?,?,'UNKNOWN','{}','{}',0,0)",
                    ('capacity-followup:old'+str(n), 'fixture'+str(n), follow.SCOPE))
        self.event(2)
        blocked = follow.reconcile(self.root)
        self.assertEqual(blocked['state'], 'BLOCKED'); self.assertEqual(blocked['through_sequence'], 11)

    def test_non_due_original_tick_reconciles_without_sampling_or_sender(self):
        self.event(2)
        with patch.object(capacity, 'collect_sample', side_effect=AssertionError('not due')):
            self.assertFalse(capacity.tick(self.root, now=1001))
        self.assertEqual(len(self.tasks()), 1)

    def test_readers_are_passive_and_visible_in_capacity_mailbox_and_work(self):
        self.event(2); follow.reconcile(self.root)
        before = self.archive.path.read_bytes()
        from reporting.engineering_relay import proposals
        from reporting.secretary_presentation import work_status
        self.assertEqual(proposals(self.archive)['items'][0]['engineering_status']['state'], 'QUEUED_READ_ONLY')
        self.assertIn('容量', work_status(self.archive, self.store, '容量'))
        self.assertEqual(capacity.read(self.root, now=1001)['engineering_followup']['items'][0]['state'], 'QUEUED_READ_ONLY')
        self.assertEqual(self.archive.path.read_bytes(), before)

    def test_noncapacity_tasks_and_notification_unknown_are_not_mutated(self):
        with closing(self.archive.connect()) as c, c:
            c.execute("INSERT INTO secretary_engineering_tasks VALUES ('original-B','original-instruction','original-scope','UNKNOWN','{}','{}',0,0)")
        self.event(2)
        with closing(self.store.connect()) as c, c:
            c.execute("UPDATE notification_outbox SET status='UNKNOWN'")
        follow.reconcile(self.root)
        with closing(self.archive.connect()) as c:
            self.assertEqual(c.execute("SELECT state FROM secretary_engineering_tasks WHERE id='original-B'").fetchone()[0], 'UNKNOWN')
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0], 'UNKNOWN')

    def test_cursor_symlink_and_hardlink_never_overwrite_protected_evidence(self):
        self.event(2)
        protected = self.root/'protected-source'; protected.write_text('preserve original')
        cursor = self.root/'runtime/capacity-engineering.json'
        cursor.symlink_to(protected)
        self.assertEqual(follow.reconcile(self.root)['state'],'BLOCKED')
        self.assertEqual(protected.read_text(),'preserve original')
        cursor.unlink()  # Isolated fabricated symlink only.
        temporary = self.root/'runtime/capacity-engineering.tmp'
        import os
        os.link(protected,temporary)
        self.assertEqual(follow.reconcile(self.root)['state'],'BLOCKED')
        self.assertEqual(protected.read_text(),'preserve original')
