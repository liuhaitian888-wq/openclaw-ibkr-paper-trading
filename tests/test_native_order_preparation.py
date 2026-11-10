from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import unittest
from trading.native_order_preparation import initialize_schema, record_preparation, get_preparation
from trading.audit import AuditLog
from tests import test_entry_admission as admission_fixtures


class NativeOrderPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=admission_fixtures.EntryAdmissionTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.audit=self.fixture.audit
        self.fixture.funding(10000);self.fixture.reserve(self.fixture.proposal('prepared'),cash=True)
        self.at=datetime.now(timezone.utc);stamp=self.at.isoformat()
        with closing(self.audit._connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');initialize_schema(c)
        self.proof=dict(source='NATIVE_PREWIRE_IDENTITY',environment='PAPER',account='DUQ503649',
            broker_epoch='verified-epoch',connection_generation='execution-session',client_id=22,
            parent_order_id=11,stop_order_id=12,
            contract=dict(source='NATIVE_CONTRACT_DETAILS',complete=True,connection_generation='execution-session',
                request_id=61001,symbol='BAC',sec_type='STK',currency='USD',con_id=9029,
                primary_exchange='NYSE',min_tick='.01',observed_at=stamp),
            next_valid_id=dict(source='NATIVE_NEXT_VALID_ID',value=11,connection_generation='execution-session',observed_at=stamp))
    def prepare(self,identity='prepared',proof=None):
        with closing(self.audit._connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            return record_preparation(c,identity,self.proof if proof is None else proof,self.at.isoformat())
    def test_preparation_survives_restart_but_is_not_ack_or_mutation_permission(self):
        result=self.prepare()
        self.assertFalse(result['broker_acknowledged']);self.assertFalse(result['mutation_authorized'])
        self.assertFalse(result['wire_prices_verified']);self.assertFalse(result['partial_fill_coverage_verified'])
        self.assertTrue(result['requires_final_wire_admission'])
        self.audit=AuditLog(self.audit._path)
        with closing(self.audit._connect()) as c:
            self.assertEqual(get_preparation(c,'prepared'),result)
            self.assertEqual(c.execute('SELECT state FROM entry_cash_claims').fetchone()[0],'RESERVED')
        self.assertEqual(self.audit.get('prepared')['status'],'RESERVED')
    def test_same_preparation_is_idempotent_and_changed_identity_never_overwrites(self):
        first=self.prepare();self.assertEqual(self.prepare(),first)
        bad=deepcopy(self.proof);bad['parent_order_id']=13;bad['stop_order_id']=14
        with self.assertRaises(PermissionError):self.prepare(proof=bad)
        with closing(self.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM native_order_preparations').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM native_prepared_order_ids').fetchone()[0],2)
    def test_zero_parent_overflow_or_mixed_connection_is_rejected(self):
        for mutate in (lambda p:p.update(parent_order_id=0,stop_order_id=1),
                       lambda p:p.update(parent_order_id=2147483647,stop_order_id=2147483648),
                       lambda p:p['contract'].update(connection_generation='old'),
                       lambda p:p['contract'].update(con_id=0),
                       lambda p:p['contract'].update(currency='EUR'),
                       lambda p:p['contract'].update(symbol='KO'),
                       lambda p:p.update(account='OTHER')):
            proof=deepcopy(self.proof);mutate(proof)
            with self.assertRaises(PermissionError):self.prepare(proof=proof)
        with closing(self.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM native_order_preparations').fetchone()[0],0)
    def test_stale_contract_or_native_id_receipt_is_not_relabelled_current(self):
        for field in ('contract','next_valid_id'):
            proof=deepcopy(self.proof);proof[field]['observed_at']=(self.at-timedelta(seconds=11)).isoformat()
            with self.assertRaises(PermissionError):self.prepare(proof=proof)
    def test_started_history_prevents_reprepare_even_after_status_relabel(self):
        self.prepare();self.audit.mark_submission_started('prepared')
        self.audit.update('prepared','RESERVED','Operator label is not no-send proof')
        with self.assertRaisesRegex(PermissionError,'Started occurrence'):self.prepare()
        with closing(self.audit._connect()) as c:self.assertIsNotNone(get_preparation(c,'prepared'))
    def test_native_id_collision_rolls_back_even_if_caller_catches_and_commits(self):
        self.prepare();self.fixture.reserve(self.fixture.proposal('other'),cash=True)
        self.at=datetime.now(timezone.utc)
        proof=deepcopy(self.proof);proof.update(parent_order_id=10,stop_order_id=11);proof['next_valid_id']['value']=10
        with closing(self.audit._connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(PermissionError,'identity already reserved'):record_preparation(c,'other',proof,self.at.isoformat())
        with closing(self.audit._connect()) as c:
            self.assertIsNone(get_preparation(c,'other'))
            self.assertEqual(c.execute('SELECT count(*) FROM native_prepared_order_ids').fetchone()[0],2)
    def test_incomplete_id_reservation_is_not_silently_repaired(self):
        self.prepare()
        with closing(self.audit._connect()) as c,c:
            c.execute("DELETE FROM native_prepared_order_ids WHERE leg='PROTECTION'")
        with self.assertRaisesRegex(ValueError,'reservation set differs'):self.prepare()
        with closing(self.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM native_prepared_order_ids').fetchone()[0],1)
    def test_corrupt_stored_content_or_forged_permission_never_becomes_wire_authority(self):
        self.prepare()
        with closing(self.audit._connect()) as c,c:
            c.execute("UPDATE native_order_preparations SET proof_json='{}'")
        with closing(self.audit._connect()) as c:
            with self.assertRaises(ValueError):get_preparation(c,'prepared')
    def test_no_transaction_or_absent_reserved_claim_cannot_prepare(self):
        with closing(self.audit._connect()) as c:
            with self.assertRaises(PermissionError):record_preparation(c,'prepared',self.proof,self.at.isoformat())
        self.fixture.reserve(self.fixture.proposal('unfunded'))
        with self.assertRaises(PermissionError):self.prepare(identity='unfunded')
