from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reporting.agent_secretary import SecretaryArchive
from reporting.database_console import DATABASES
from reporting.engineering_tasks import (EXECUTOR, SCOPE, claim, control_receipt, diagnostic, enqueue,
    initialize, native_instruction, policy, run_once)
from reporting.incidents import IncidentStore
from reporting.secretary_queue import accept_update, initialize as inbox_initialize


class EngineeringTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.now = 1000
        self.a = SecretaryArchive(self.root/'agent_secretary.sqlite3', clock=lambda: self.now)
        inbox_initialize(self.a); initialize(self.a)
        self.store = IncidentStore(self.root/'runtime/recovery.sqlite3')
        self.config = {'owner_user_id': 7, 'owner_private_chat_id': 7, 'owner_private_verified': True}
        self.value = {'approved': True, 'model_owner': 'cloud_oauth', 'model_owner_since': 900, 'grants_trading_permission': False,
            'engineering_scope': {'approved': True, 'scope': SCOPE, 'executor': EXECUTOR,
                'version': 'one-diagnostic', 'since': 900, 'expires': 2000, 'max_tasks': 1,
                'grants_trading_permission': False, 'grants_deployment_permission': False}}
        self.home = self.root/'secretary-oauth'; self.home.mkdir(mode=0o700)
        (self.home/'auth.json').write_text('{"auth_mode":"chatgpt"}')
        (self.home/'auth.json').chmod(0o600)
        (self.root/'secretary-oauth-empty').mkdir()
        self.calls = 0

    def update(self, uid=1, **change):
        message = {'from': {'id': 7, 'is_bot': False}, 'chat': {'id': 7, 'type': 'private'},
                   'text': '/codex dbcheck', 'date': 1000, 'message_id': uid}
        message.update(change)
        return {'update_id': uid, 'message': message}

    def receive(self, uid=1, **change):
        self.assertTrue(accept_update(self.a, self.update(uid, **change), self.config, armed_at=900))

    def backend(self, evidence, *, record, **kwargs):
        self.calls += 1
        record('THREAD_CREATED', {'thread_id': 'native-thread'})
        record('TURN_ACCEPTED', {'thread_id': 'native-thread', 'turn_id': 'native-turn'})
        result = {'thread_id': 'native-thread', 'turn_id': 'native-turn', 'status': 'completed',
                  'summary': '已核对登记库；缺失与陈旧保持明确。'}
        record('TURN_COMPLETED', result)
        return result

    def run_task(self, backend=None):
        # Freeze archive time only, not deadlines used by actual SQLite operations.
        with patch('reporting.agent_secretary.SecretaryArchive', return_value=self.a):
            return run_once(self.root, self.config, self.value, home=self.home, backend=backend or self.backend)

    def task_rows(self):
        with closing(self.a.connect()) as c:
            return c.execute('SELECT id,state,native FROM secretary_engineering_tasks').fetchall()

    def test_native_receiver_rejects_group_forward_bot_and_edited_updates(self):
        for change in ({'chat': {'id': 7, 'type': 'group'}}, {'forward_origin': {'type': 'user'}},
                       {'from': {'id': 8, 'is_bot': False}}, {'from': {'id': 7, 'is_bot': True}}):
            self.assertFalse(accept_update(self.a, self.update(**change), self.config, armed_at=900))
        update = self.update(); update['edited_message'] = update.pop('message')
        self.assertFalse(accept_update(self.a, update, self.config, armed_at=900))
        self.assertEqual([], self.task_rows())

    def test_model_suggestion_old_archive_and_arbitrary_command_cannot_queue(self):
        self.a.append('model-proposal', 'der-secretary', origin='MODEL', kind='ENGINEERING_HANDOFF',
            payload={'request': '/codex dbcheck'})
        self.receive(text='/codex run arbitrary shell')
        self.assertTrue(accept_update(self.a, self.update(2, date=800), self.config, armed_at=700))
        # Legacy native events were valid chat records but lack new executable provenance.
        self.a.append('telegram:7:3', 'der-secretary', origin='USER', kind='CONTROL_INSTRUCTION',
            payload={'source': 'Telegram native owner message', 'text': '/codex dbcheck',
                     'chat_id': 7, 'message_id': 3, 'update_id': 3, 'timestamp': 1000})
        with closing(self.a.connect()) as c, c:
            c.execute('INSERT INTO secretary_received VALUES (?,?)', ('telegram:7:3', self.now))
        enqueue(self.a, self.config, self.value)
        self.assertEqual([], self.task_rows())

    def test_one_native_scope_task_shared_budget_and_idempotent_completion_private_outbox(self):
        self.receive(); self.receive(2)
        self.assertEqual('SUCCEEDED', self.run_task())
        self.assertEqual('IDLE', self.run_task())
        self.assertEqual(1, self.calls); self.assertEqual(1, len(self.task_rows()))
        with closing(self.a.connect()) as c:
            runs = c.execute("SELECT model,state FROM secretary_runs WHERE model='gpt-6.1-sol'").fetchall()
        self.assertEqual([('gpt-6.1-sol', 'SUCCEEDED')], runs)
        reports = list((self.root/'engineering/codex-executor').glob('*/report.json'))
        self.assertEqual(1, len(reports))
        data = json.loads(reports[0].read_text())
        self.assertEqual(4, len(data['evidence']['databases']))
        self.assertEqual('native-turn', data['native']['turn_id'])
        with closing(self.store.connect()) as c:
            rows = c.execute('SELECT incident_key,payload FROM notification_outbox').fetchall()
        self.assertEqual(2, len(rows))
        for _, payload in rows:
            self.assertTrue(json.loads(payload)['requires_response'])
            self.assertEqual('CONTROL', json.loads(payload)['message_role'])
        self.assertEqual(0o600, reports[0].stat().st_mode & 0o777)

    def test_unknown_and_started_never_replay_or_take_second_instruction(self):
        self.receive()
        def uncertain(evidence, *, record, **kwargs):
            self.calls += 1; record('THREAD_CREATED', {'thread_id': 'retained'})
            raise TimeoutError()
        self.assertEqual('UNKNOWN', self.run_task(uncertain))
        self.receive(2)
        self.assertEqual('IDLE', self.run_task())
        self.assertEqual(1, self.calls)
        self.assertEqual('UNKNOWN', self.task_rows()[0][1])
        self.assertEqual('retained', json.loads(self.task_rows()[0][2])['thread_id'])

    def test_started_after_crash_is_preserved_without_backend_call(self):
        self.receive(); enqueue(self.a, self.config, self.value)
        self.assertIsNotNone(claim(self.a, self.config, self.value))
        self.assertEqual('STARTED_REQUIRES_RECONCILIATION', self.run_task())
        self.assertEqual(0, self.calls)

    def test_control_receipt_is_queued_not_native_acceptance_and_used_scope_is_honest(self):
        self.receive()
        self.assertIn('已排队', control_receipt(self.a, self.config, self.value, 'telegram:7:1'))
        self.receive(2)
        self.assertIn('不能再提交', control_receipt(self.a, self.config, self.value, 'telegram:7:2'))
        self.assertEqual(0, self.calls)

    def test_completed_event_survives_checkpoint_projection_loss_without_native_retry(self):
        self.receive()
        with patch('reporting.engineering_tasks.finish', side_effect=OSError()):
            self.assertEqual('UNKNOWN', self.run_task())
        with closing(self.a.connect()) as c, c:
            c.execute("UPDATE secretary_engineering_tasks SET native=?", (json.dumps({'thread_id':'native-thread','turn_id':'native-turn','stage':'TURN_ACCEPTED'}),))
        self.assertEqual('COMPLETION_RECONCILED', self.run_task())
        self.assertEqual(1,self.calls)

    def test_completed_native_receipt_repairs_archive_artifact_and_outbox_without_model(self):
        self.receive()
        with patch('reporting.engineering_tasks.finish', side_effect=OSError('simulated disk interruption')):
            self.assertEqual('UNKNOWN', self.run_task())
        self.assertEqual('STARTED', self.task_rows()[0][1])
        self.assertEqual('COMPLETION_RECONCILED', self.run_task())
        self.assertEqual('SUCCEEDED', self.task_rows()[0][1]); self.assertEqual(1, self.calls)
        with closing(self.store.connect()) as c, c:
            c.execute("DELETE FROM notification_outbox WHERE incident_key LIKE 'secretary:engineering:%'")
        self.run_task()
        with closing(self.store.connect()) as c:
            self.assertEqual(1, c.execute("SELECT count(*) FROM notification_outbox WHERE incident_key LIKE 'secretary:engineering:%'").fetchone()[0])

    def test_shared_twenty_four_task_budget_scope_expiry_and_policy_conflict(self):
        self.receive()
        with closing(self.a.connect()) as c, c:
            for number in range(24):
                c.execute("INSERT INTO secretary_runs VALUES (?,?,'gpt-6.1-sol','FAILED',NULL,?)",
                          ('spent'+str(number), 'telegram:7:1', self.now))
        enqueue(self.a, self.config, self.value)
        self.assertIsNone(claim(self.a, self.config, self.value)); self.assertEqual('QUEUED', self.task_rows()[0][1])
        self.now = 2001
        with self.assertRaises(PermissionError): claim(self.a, self.config, self.value)
        self.now = 1000; self.value['engineering_scope']['expires'] = 1900
        with self.assertRaises(PermissionError): claim(self.a, self.config, self.value)

    def test_historical_mac_started_is_retained_and_current_owner_started_blocks_new_claim(self):
        self.receive()
        with closing(self.a.connect()) as c, c:
            c.execute("INSERT INTO secretary_runs VALUES ('old-mac','telegram:7:1','gpt-6.1-sol','STARTED',NULL,800)")
            c.execute("INSERT INTO secretary_runs VALUES ('current-cloud','telegram:7:1','gpt-6.1-sol','STARTED',NULL,950)")
        enqueue(self.a, self.config, self.value)
        self.assertIsNone(claim(self.a, self.config, self.value))
        self.a.finish_run('current-cloud', state='UNKNOWN')
        self.assertEqual('SUCCEEDED', self.run_task())
        with closing(self.a.connect()) as c:
            self.assertEqual(('STARTED',), c.execute("SELECT state FROM secretary_runs WHERE occurrence='old-mac'").fetchone())
            self.assertEqual(('UNKNOWN',), c.execute("SELECT state FROM secretary_runs WHERE occurrence='current-cloud'").fetchone())

    def test_fixed_registry_diagnostics_read_real_table_counts_missing_and_stale_sources(self):
        for database, _, _, probes in DATABASES[:2]:
            p = self.root/database
            with closing(sqlite3.connect(p)) as c, c:
                c.execute('CREATE TABLE sentinel(value TEXT)')
                for table, column in probes:
                    c.execute('CREATE TABLE IF NOT EXISTS "'+table+'" ("'+column+'" REAL)')
                    c.execute('INSERT INTO "'+table+'" VALUES (1)')
        evidence = diagnostic(self.root, now=1000)
        self.assertEqual([x[0] for x in DATABASES], [x['database'] for x in evidence['databases']])
        self.assertEqual(3, evidence['databases'][0]['table_count_evidence']['rows'][0]['table_count'])
        self.assertEqual('STALE_PROBE', evidence['databases'][0]['probe_freshness'])
        with closing(sqlite3.connect(self.root/DATABASES[0][0])) as c:
            self.assertEqual(0, c.execute('SELECT count(*) FROM sentinel').fetchone()[0])

    def test_locked_registered_source_is_bounded_and_other_sources_still_reported(self):
        p=self.root/'trading_audit.sqlite3'
        with closing(sqlite3.connect(p)) as locked:
            locked.execute('CREATE TABLE sentinel(value)');locked.commit();locked.execute('BEGIN EXCLUSIVE')
            evidence=diagnostic(self.root,now=1000)
        self.assertEqual(4,len(evidence['databases']))
        self.assertEqual('UNAVAILABLE_OR_BUDGET',evidence['databases'][0]['table_count_evidence']['state'])
        self.assertEqual('UNKNOWN',evidence['databases'][0]['probe_freshness'])

    def test_symlink_report_root_fails_without_writing_outside_scope(self):
        self.receive(); outside = self.root/'outside'; outside.mkdir()
        (self.root/'engineering').symlink_to(outside, target_is_directory=True)
        self.assertEqual('UNKNOWN', self.run_task())
        self.assertEqual([], list(outside.iterdir())); self.assertEqual(0, self.calls)
