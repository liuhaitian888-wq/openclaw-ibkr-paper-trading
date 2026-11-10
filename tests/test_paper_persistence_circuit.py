from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import json,sqlite3,unittest
from trading.cash_guard import enforce
from reporting.health import resolve_modules
from tests import test_native_cash_owner as fixtures


class PaperPersistenceCircuitTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeCashOwnerTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.monitor=self.fixture.monitor;self.client=self.fixture.client
        self.marker=self.fixture.root/'runtime/paper-local-persistence-fault.json'

    def locked_callback(self):
        with closing(sqlite3.connect(self.monitor.coordinator.path)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            with patch.object(self.client,'disconnect') as disconnect,patch.object(self.client,'placeOrder') as trade:
                self.client.error(-1,2104,'market data farm connected')
                disconnect.assert_not_called();trade.assert_not_called()
            self.assertTrue(self.client.isConnected());self.assertTrue(self.monitor.persistence_circuit.blocked)
            self.assertFalse(self.monitor._complete());self.assertTrue(self.marker.exists())
            blocker.rollback()

    def test_real_sqlite_lock_does_not_escape_decoder_callback_or_grant_funding(self):
        self.locked_callback()
        (self.fixture.root/'runtime/FUNDING_POLICY_REQUIRED').touch()
        with self.assertRaisesRegex(PermissionError,'local persistence'):
            enforce(self.fixture.root,SimpleNamespace(side='BUY',quantity=1,limit_price=1))
        self.assertEqual(self.marker.stat().st_mode&0o077,0)

    def test_probe_does_not_restore_old_end_markers_and_uses_same_connection(self):
        self.locked_callback()
        for name in ('reqAllOpenOrders','reqCompletedOrders','reqExecutions','reqPositions'):
            setattr(self.client,name,Mock())
        circuit=self.monitor.persistence_circuit
        self.assertFalse(circuit.poll(self.client,monotonic=lambda:0))
        self.assertEqual(self.monitor.state['ends'],[]);self.assertTrue(self.marker.exists())
        self.assertFalse(self.monitor._complete())
        self.client.reqPositions.assert_called_once()
        self.fixture.now+=1
        for end in ('positions','orders','completed_orders','executions'):self.monitor.end(end)
        self.monitor.state['last_server_reply']=self.fixture.now
        self.assertTrue(circuit.poll(self.client,monotonic=lambda:6))
        self.assertFalse(self.marker.exists());self.assertTrue(self.monitor._complete())
        self.assertEqual(len(list(self.marker.parent.glob('paper-local-persistence-reconciled-*.json'))),1)
        self.assertEqual(self.monitor.coordinator.observations()['LOCAL_STATE']['state'],'HEALTHY')

    def test_unknown_commit_outcome_is_not_automatically_recovered(self):
        self.monitor.persistence_circuit.block(sqlite3.OperationalError('unspecified outcome'),'fixture')
        client=SimpleNamespace(isConnected=Mock(return_value=True),accounts=['DUQ503649'],reconcile=Mock())
        self.assertFalse(self.monitor.persistence_circuit.poll(client,monotonic=lambda:0))
        client.reconcile.assert_not_called();self.assertTrue(self.marker.exists())

    def test_shared_registry_latch_survives_generic_healthy_observation(self):
        self.monitor.coordinator.observe('LOCAL_STATE','FAILED',local_persistence_failure={'id':'fault'})
        self.monitor.coordinator.observe('LOCAL_STATE','HEALTHY',freshness='FRESH',reason='Unrelated generic probe')
        row=resolve_modules(self.monitor.coordinator.observations())['LOCAL_STATE']
        self.assertEqual(row['state'],'FAILED')

    def test_admission_never_allows_socket_after_failed_durable_reservation(self):
        with closing(sqlite3.connect(self.monitor.coordinator.path)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            self.assertFalse(self.monitor.admit_connection('existing-gateway',api_listening=True))
            self.assertTrue(self.monitor.persistence_circuit.blocked)
            self.assertTrue(self.marker.exists())
            blocker.rollback()

    def test_directory_sync_failure_keeps_gate_closed(self):
        with patch.object(self.monitor.persistence_circuit,'_sync_directory',side_effect=OSError('fixture directory sync failed')):
            self.locked_callback()
        self.assertTrue(self.monitor.persistence_circuit.failure.get('marker_write_failed'))
        client=SimpleNamespace(isConnected=Mock(return_value=True),accounts=['DUQ503649'],reconcile=Mock())
        self.assertFalse(self.monitor.persistence_circuit.poll(client,monotonic=lambda:0))
        client.reconcile.assert_not_called();self.assertTrue(self.marker.exists())

    def test_native_error_record_failure_does_not_kill_decoder_or_hide_upstream_loss(self):
        error=sqlite3.OperationalError('fixture locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch.object(self.monitor,'_record',side_effect=error),patch.object(self.client,'disconnect') as disconnect:
            self.client.error(-1,1100,'upstream lost')
            disconnect.assert_not_called()
        self.assertFalse(self.monitor.state['upstream_connected'])
        self.assertTrue(self.monitor.persistence_circuit.failure['requires_operator'])
        self.assertTrue(list(self.marker.parent.glob('paper-persistence-evidence-*.json')))

    def test_canonical_fee_failure_keeps_socket_and_retains_evidence(self):
        error=sqlite3.OperationalError('fixture locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch.object(self.monitor.audit,'record_execution_fee',side_effect=error),patch.object(self.client,'disconnect') as disconnect:
            self.client.commissionReport(SimpleNamespace(execId='native-exec',commission=1,currency='USD'))
            disconnect.assert_not_called()
        self.assertTrue(self.monitor.state['connected']);self.assertFalse(self.monitor._complete())
        self.assertTrue(self.monitor.persistence_circuit.failure['requires_operator'])
        files=list(self.marker.parent.glob('paper-persistence-evidence-*.json'))
        self.assertEqual(len(files),1)
        self.assertIn('native-exec',files[0].read_text())

    def test_failed_archive_directory_sync_restores_marker_and_never_reports_recovery(self):
        self.locked_callback()
        for name in ('reqAllOpenOrders','reqCompletedOrders','reqExecutions','reqPositions'):setattr(self.client,name,Mock())
        circuit=self.monitor.persistence_circuit;circuit.poll(self.client,monotonic=lambda:0)
        self.fixture.now+=1
        for end in ('positions','orders','completed_orders','executions'):self.monitor.end(end)
        self.monitor.state['last_server_reply']=self.fixture.now
        with patch.object(circuit,'_sync_directory',side_effect=[OSError('fixture sync failure'),None]):
            self.assertFalse(circuit.poll(self.client,monotonic=lambda:6))
        self.assertTrue(self.marker.exists());self.assertTrue(circuit.blocked)
        self.assertEqual(self.monitor.coordinator.observations()['LOCAL_STATE']['state'],'FAILED')

    def test_cash_guard_reads_persistent_latch_without_marker(self):
        from tests import test_entry_admission as admission
        fixture=admission.EntryAdmissionTests();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.funding()
        with closing(sqlite3.connect(fixture.runtime/'recovery.sqlite3')) as c,c:
            c.execute('CREATE TABLE module_observations(name TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            c.execute('INSERT INTO module_observations VALUES(?,?)',('LOCAL_STATE',json.dumps({'local_persistence_failure':{'id':'fault'}})))
        with self.assertRaisesRegex(PermissionError,'Local journal recovery'):
            enforce(fixture.root,fixture.proposal('blocked'))

    def test_callback_record_spills_exact_rows_and_recovers_without_replaying_callback(self):
        self.locked_callback()
        self.monitor._record('fixture_native_event',{'native_id':'exact-occurrence'})
        self.assertTrue(list(self.marker.parent.glob('paper-persistence-record-*.json')))
        for name in ('reqAllOpenOrders','reqCompletedOrders','reqExecutions','reqPositions'):setattr(self.client,name,Mock())
        circuit=self.monitor.persistence_circuit;circuit.poll(self.client,monotonic=lambda:0)
        with closing(self.monitor.coordinator.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM paper_callback_events WHERE kind='fixture_native_event'").fetchone()[0],1)
        self.assertFalse(list(self.marker.parent.glob('paper-persistence-record-*.json')))
        self.assertTrue(list(self.marker.parent.glob('paper-persistence-record-*.reconciled.*')))

    def test_recovery_publication_tail_is_committed_before_unblocking(self):
        self.locked_callback()
        for name in ('reqAllOpenOrders','reqCompletedOrders','reqExecutions','reqPositions'):setattr(self.client,name,Mock())
        circuit=self.monitor.persistence_circuit;circuit.poll(self.client,monotonic=lambda:0)
        self.fixture.now+=1
        for end in ('positions','orders','completed_orders','executions'):self.monitor.end(end)
        self.monitor.state['last_server_reply']=self.fixture.now
        original=self.monitor._publish_impl
        def publish_tail():
            result=original();self.monitor._record('recovery_tail',{'proof':'original'});return result
        with patch.object(self.monitor,'_publish_impl',side_effect=publish_tail):
            self.assertTrue(circuit.poll(self.client,monotonic=lambda:6))
        self.assertFalse(list(self.marker.parent.glob('paper-persistence-record-*.json')))
        with closing(self.monitor.coordinator.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM paper_callback_events WHERE kind='recovery_tail'").fetchone()[0],1)

    def test_cash_health_sqlite_failure_does_not_poison_transport(self):
        request=self.fixture.request();self.fixture.feed(request)
        error=sqlite3.OperationalError('fixture locked');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch.object(self.monitor.coordinator,'observe',side_effect=error):
            self.client.accountUpdateMultiEnd(request)
        self.assertTrue(self.monitor.persistence_circuit.blocked)
        self.assertFalse(self.client.cashbook_collector.poisoned)
        self.assertFalse(self.monitor.cashbook_publication_state.get('blocked',False))
        self.assertTrue(self.client.isConnected())
        self.client.poll_cashbook()  # No RuntimeError to reconnect a healthy SDK.
