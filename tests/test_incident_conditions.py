from contextlib import closing, nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.incidents import IncidentStore
from reporting.incident_conditions import protection_conditions
from trading.position_guard import protection_evidence_complete
from ops.cloud import monitoring_guard

NOW = 1792764000
STAMP = datetime.fromtimestamp(NOW, timezone.utc).isoformat()


def guard(symbol='AAPL', warning=True, complete=False, **kwargs):
    flags = dict(duplicate_stop_warning=False, missing_stop_warning=warning,
                 overprotected_warning=False, underprotected_warning=False)
    return dict(source='position_guard', timestamp=STAMP, account='DU1',
                protection_evidence_complete=complete,
                symbols=[dict(symbol=symbol, position_covered_by_stop=not warning, **flags)], **kwargs)


def paper(stamp=STAMP, **kwargs):
    return dict(observed_at=stamp, source='REAL_IBKR', environment='PAPER', account_id='DU1',
                complete=True, resources={'connected_after_close': False}, **kwargs)


class ConditionTests(unittest.TestCase):
    def test_protection_warning_then_explicit_fresh_complete_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.jsonl'
            store = IncidentStore(Path(tmp) / 'state.sqlite3', clock=lambda: NOW)
            collector = IncidentCollector(store)
            collector.protection_reports(path, 'DU1', guard=True)
            path.write_text(json.dumps(guard()) + '\n')
            self.assertEqual(collector.protection_reports(path, 'DU1', guard=True), 1)
            alert = store.claim()
            self.assertEqual(alert['payload']['severity'], 'RED')
            store.finish(alert['id'], 'SMTP_ACCEPTED')
            # Incomplete healthy-looking report is not recovery.
            with path.open('a') as f:
                f.write(json.dumps(guard(warning=False)) + '\n')
            collector.protection_reports(path, 'DU1', guard=True)
            self.assertIsNone(store.claim())
            with path.open('a') as f:
                f.write(json.dumps(guard(warning=False, complete=True)) + '\n')
            collector.protection_reports(path, 'DU1', guard=True)
            self.assertEqual(store.claim()['kind'], 'RECOVERY')
            self.assertEqual(collector.protection_reports(path, 'DU1', guard=True), 0)

    def test_rejected_protection_unknown_account_is_not_falsely_resolved(self):
        report = dict(source='position_protection', mode='PAPER', timestamp=STAMP,
                      records=[dict(symbol='AAPL', order_type='STP', state_stale=True,
                                    confirmation_statuses={'11': 'Rejected'})])
        events = list(protection_conditions(report, 'DU1', NOW))
        self.assertEqual(events[0][0], 'protection-unverified:AAPL')
        self.assertFalse(events[0][2])
        self.assertEqual(events[0][1]['severity'], 'RED')
        for status in ('Cancelled', 'Inactive', 'ApiCancelled'):
            report['records'][0]['confirmation_statuses']['11'] = status
            self.assertEqual(len(list(protection_conditions(report, 'DU1', NOW))), 1)
        report['records'][0]['confirmation_statuses']['11'] = 'Submitted'
        self.assertEqual(list(protection_conditions(report, 'DU1', NOW)), [])

    def test_stale_wrong_account_and_late_protection_cannot_restore(self):
        self.assertFalse(any(event[2] for event in protection_conditions(guard(warning=False, complete=True), 'DU1', NOW + 601)))
        mismatch = list(protection_conditions(guard(), 'DU2', NOW))
        self.assertEqual(mismatch[0][1]['severity'], 'RED')
        self.assertEqual(mismatch[0][1]['scope'], 'ACCOUNT')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.jsonl'
            store = IncidentStore(Path(tmp) / 'state.sqlite3', clock=lambda: NOW)
            collector = IncidentCollector(store)
            collector.protection_reports(path, 'DU1', guard=True)
            report = guard()
            path.write_text(json.dumps(report) + '\n')
            collector.protection_reports(path, 'DU1', guard=True)
            first = store.claim(); store.finish(first['id'], 'SMTP_ACCEPTED')
            late = guard(warning=False, complete=True)
            late['timestamp'] = datetime.fromtimestamp(NOW - 1, timezone.utc).isoformat()
            with path.open('a') as f:
                f.write(json.dumps(late) + '\n')
            collector.protection_reports(path, 'DU1', guard=True)
            self.assertIsNone(store.claim())

    def test_complete_protection_proof_rejects_partial_contingent_and_wrong_account(self):
        positions = dict(account='DU1', status='ok', snapshot_complete=True, positions=[dict(position_qty=2)], errors=[])
        order = dict(account='DU1', status='Submitted', order_type='STP', order_status={'remaining': 2},
                     total_quantity=2, parent_id=0, oca_group='')
        orders = dict(account='DU1', status='ok', snapshot_complete=True, open_orders=[order], errors=[])
        self.assertTrue(protection_evidence_complete(positions, orders))
        for key, value in [('account', 'DU2'), ('status', 'Inactive'), ('parent_id', 1), ('oca_group', 'oco'), ('order_status', {'remaining': 1})]:
            with self.subTest(key=key):
                orders['open_orders'] = [{**order, key: value}]
                self.assertFalse(protection_evidence_complete(positions, orders))
        orders['open_orders'] = [order]
        positions['snapshot_complete'] = False
        self.assertFalse(protection_evidence_complete(positions, orders))

    def test_runtime_service_and_auth_fault_recovery_do_not_grant_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); host = root/'host.json'; readback = root/'paper.json'
            store = IncidentStore(root/'state.sqlite3', clock=lambda: NOW)
            collector = IncidentCollector(store)
            base_host = dict(observed_at=STAMP, services={'ibkr-gateway': 'active', 'ibkr-api': 'inactive'},
                service_details={'ibkr-api': {'unit_file_state': 'disabled'}})
            host.write_text(json.dumps(base_host)); readback.write_text(json.dumps(paper()))
            collector.runtime_snapshots(host, readback, 'DU1')
            self.assertIsNone(store.claim())
            bad_stamp = datetime.fromtimestamp(NOW+1, timezone.utc).isoformat()
            store.clock = lambda: NOW+1
            host.write_text(json.dumps({**base_host, 'observed_at': bad_stamp, 'services': {'ibkr-gateway': 'failed', 'ibkr-api': 'inactive'}}))
            readback.write_text(json.dumps(dict(observed_at=bad_stamp, complete=False, environment='PAPER', status='AUTH_OR_CONNECTION_REQUIRED')))
            collector.runtime_snapshots(host, readback, 'DU1')
            notifications = []
            while (item := store.claim()) is not None:
                notifications.append(item)
                self.assertFalse(item['payload']['grants_trading_permission'])
                store.finish(item['id'], 'SMTP_ACCEPTED')
            self.assertEqual(len(notifications), 2)  # Disabled API is not an outage.
            self.assertFalse(any('MFA expired' in item['payload']['reason'] for item in notifications))
            store.clock = lambda: NOW+2
            good_stamp = datetime.fromtimestamp(NOW+2, timezone.utc).isoformat()
            host.write_text(json.dumps({**base_host, 'observed_at': good_stamp}))
            readback.write_text(json.dumps(paper(good_stamp)))
            collector.runtime_snapshots(host, readback, 'DU1')
            self.assertEqual(store.claim()['kind'], 'RECOVERY')

    def test_missing_stale_invalid_future_and_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); host=root/'host.json'; readback=root/'paper.json'
            store=IncidentStore(root/'state.sqlite3', clock=lambda: NOW)
            collector=IncidentCollector(store)
            host.write_text(json.dumps(dict(observed_at=STAMP, services={'ibkr-gateway': 'active'})))
            readback.write_text(json.dumps(paper()))
            collector.runtime_snapshots(host, readback, 'DU1')
            store.clock=lambda: NOW+601
            collector.runtime_snapshots(host, readback, 'DU1')
            first=store.claim(); self.assertEqual(first['kind'], 'ALERT')
            store.finish(first['id'], 'SMTP_ACCEPTED')
            second=store.claim(); store.finish(second['id'], 'SMTP_ACCEPTED')
            self.assertEqual(collector.runtime_snapshots(host, readback, 'DU1'), 0)
            readback.write_text('{bad json')
            collector.runtime_snapshots(host, readback, 'DU1')  # No false recovery.
            self.assertIsNone(store.claim())
            stamp=datetime.fromtimestamp(NOW+602, timezone.utc).isoformat()
            store.clock=lambda: NOW+602
            bad=paper(stamp); bad['account_id']='DU2'
            readback.write_text(json.dumps(bad))
            collector.runtime_snapshots(host, readback, 'DU1')
            found=[]
            while (item:=store.claim()) is not None:
                found.append(item); store.finish(item['id'], 'SMTP_ACCEPTED')
            self.assertTrue(any(item['payload']['severity']=='RED' for item in found))
            readback.write_text(json.dumps(paper(STAMP)))
            with self.assertRaises(EvidenceChanged):
                collector.runtime_snapshots(host, readback, 'DU1')

    def test_monitoring_identity_and_maintenance_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'runtime').mkdir()
            actual=dict(commit='approved', branch='codex/paper', code_root='/approved', state_root=str(root.resolve()))
            manifest=dict(**actual, monitoring_approved=True, environment='PAPER', grants_trading_permission=False,
                          allow_during_maintenance=True)
            path=root/'runtime/monitoring-deployment.json'; path.write_text(json.dumps(manifest))
            with patch.object(monitoring_guard,'validate_workspace'), patch.object(monitoring_guard,'context',return_value=actual), patch.object(monitoring_guard,'maintenance_active',return_value=True), patch.object(monitoring_guard,'instance_lock',return_value=nullcontext()):
                with monitoring_guard.monitoring_service('test',root):
                    pass
                for changes in ({'commit':'other'}, {'allow_during_maintenance':False}, {'grants_trading_permission':True}):
                    path.write_text(json.dumps({**manifest, **changes}))
                    with self.assertRaises(RuntimeError), monitoring_guard.monitoring_service('test',root):
                        pass

    def test_bad_journal_does_not_prevent_runtime_evidence_collection(self):
        from contextlib import redirect_stdout
        import io
        from unittest.mock import Mock
        from ops.cloud.collect_incidents import collect_once
        collector=Mock()
        for name in ('module_events','unknown_operations','protection_reports','runtime_snapshots'):
            getattr(collector,name).return_value=0
        collector.rejections.side_effect=EvidenceChanged('retained checkpoint')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(collect_once(collector,Path('/isolated/reports'),Path('/isolated/runtime'),'DU1'),2)
        collector.runtime_snapshots.assert_called_once()

    def test_future_snapshot_cannot_recover_or_poison_valid_time_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); host=root/'host.json'; readback=root/'paper.json'
            store=IncidentStore(root/'state.sqlite3',clock=lambda:NOW)
            collector=IncidentCollector(store)
            host.write_text(json.dumps(dict(observed_at=STAMP,services={'ibkr-gateway':'active'})))
            readback.write_text(json.dumps(paper()))
            collector.runtime_snapshots(host,readback,'DU1')
            future=datetime.fromtimestamp(NOW+86400,timezone.utc).isoformat()
            readback.write_text(json.dumps(paper(future)))
            collector.runtime_snapshots(host,readback,'DU1')
            failure=store.claim(); self.assertEqual(failure['kind'],'ALERT')
            store.finish(failure['id'],'SMTP_ACCEPTED')
            store.clock=lambda:NOW+1
            stamp=datetime.fromtimestamp(NOW+1,timezone.utc).isoformat()
            readback.write_text(json.dumps(paper(stamp)))
            collector.runtime_snapshots(host,readback,'DU1')
            self.assertEqual(store.claim()['kind'],'RECOVERY')

    def test_successful_submission_is_not_misread_as_uncovered_failure(self):
        report=dict(source='position_protection',mode='PAPER',timestamp=STAMP,records=[
            dict(symbol='AAPL',state_stale=False,uncovered_qty=2,submitted=True,
                 confirmation_statuses={'10':'Submitted'})])
        self.assertEqual(list(protection_conditions(report,'DU1',NOW)),[])

    def test_source_to_outbox_to_smtp_and_recovery_end_to_end(self):
        from reporting.incident_mail import send_one
        from reporting.recovery import RecoveryCoordinator
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'guard.jsonl'; db=root/'recovery.sqlite3'
            coordinator=RecoveryCoordinator(db)
            store=IncidentStore(db,clock=lambda:NOW)
            collector=IncidentCollector(store)
            collector.protection_reports(path,'DU1',guard=True)
            path.write_text(json.dumps(guard())+'\n')
            collector.protection_reports(path,'DU1',guard=True)
            smtp=Mock(); smtp.__enter__=Mock(return_value=smtp); smtp.__exit__=Mock(return_value=False)
            smtp.send_message.return_value={}
            factory=Mock(return_value=smtp)
            cfg=dict(host='relay.invalid',sender='paper@example.invalid',username='fixture',relay_password='fixture')
            self.assertEqual(send_one(store,coordinator,cfg,trading_status='PAUSED',smtp_factory=factory),'SMTP_ACCEPTED')
            self.assertIn('RED',smtp.send_message.call_args.args[0]['Subject'])
            with path.open('a') as f:
                f.write(json.dumps(guard(warning=False,complete=True))+'\n')
            collector.protection_reports(path,'DU1',guard=True)
            self.assertEqual(send_one(store,coordinator,cfg,trading_status='PAUSED',smtp_factory=factory),'SMTP_ACCEPTED')
            self.assertIn('RECOVERY',smtp.send_message.call_args.args[0]['Subject'])
            self.assertEqual(IncidentCollector(IncidentStore(db)).protection_reports(path,'DU1',guard=True),0)
            self.assertEqual(send_one(store,coordinator,cfg,smtp_factory=factory),'EMPTY')
            self.assertEqual(factory.call_count,2)
            self.assertFalse((root/'trading_audit.sqlite3').exists())
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
