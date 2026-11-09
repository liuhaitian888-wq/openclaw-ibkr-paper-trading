from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import json,sqlite3,tempfile,threading,time,unittest
from trading.audit import AuditLog
from trading.models import TradeProposal
from trading.entry_admission import reserve_cash


class EntryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.runtime=self.root/'runtime';self.runtime.mkdir()
        self.audit=AuditLog(self.root/'audit.sqlite3')

    def funding(self,cash=1000):
        (self.runtime/'FUNDING_POLICY_REQUIRED').touch()
        (self.runtime/'funding-policy.json').write_text(json.dumps({'approved':True,'environment':'PAPER','account':'DUQ503649','mode':'CASH_ONLY_NO_NEW_BORROWING','allow_new_currency_debit':False,'fee_reserve_usd':5}))
        now=time.time()
        (self.runtime/'currency-book.latest.json').write_text(json.dumps({'source':'BROKER_API','account':'DUQ503649','observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'currencies':{'USD':{'amount':str(cash),'currency':'USD'}}}))
        with closing(sqlite3.connect(self.runtime/'recovery.sqlite3')) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)')
            c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps({'identity':True,'connected':True,'upstream_connected':True,'dirty':False,'ends':['positions','orders','executions','completed_orders'],'last_server_reply':now,'epoch':'verified-epoch','orders':{}}),))

    def proposal(self,key,price=100):return TradeProposal('BAC','BUY',1,price,price-1,key)

    def reserve(self,p,*,cash=False,cap=None):
        return self.audit.reserve(p,'PAPER_TRANSMIT','approved-strategy',daily_cap=cap,timezone_name='America/New_York',admission_check=(lambda c,at:reserve_cash(c,self.root,p,at)) if cash else None)

    def test_parallel_daily_check_and_intent_insert_are_one_transaction(self):
        barrier=threading.Barrier(2)
        def attempt(index):
            barrier.wait()
            try:return self.reserve(self.proposal('intent-'+str(index)),cap=150)
            except PermissionError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(sorted(results),[False,True])
        self.assertEqual(len(self.audit.list_recent(10)),1)

    def test_local_cash_claims_prevent_reusing_unseen_broker_cash(self):
        self.funding();first=self.proposal('first',600)
        self.assertTrue(self.reserve(first,cash=True));self.audit.mark_submission_started('first');self.audit.update('first','PAPER_SUBMITTED','ACK, no claim release proof')
        with self.assertRaises(PermissionError):self.reserve(self.proposal('second',400),cash=True)
        self.assertIsNone(self.audit.get('second'))
        with closing(self.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT reserved_usd,state FROM entry_cash_claims').fetchone()[:],('605','ACKNOWLEDGED_UNRECONCILED'))

    def test_unknown_claim_survives_new_service_instance_and_failed_label(self):
        self.funding(10000);p=self.proposal('uncertain')
        self.reserve(p,cash=True);self.audit.mark_submission_started(p.idempotency_key);self.audit.update(p.idempotency_key,'UNKNOWN','ACK lost')
        self.audit.update(p.idempotency_key,'FAILED','Label alone is not native proof')
        self.audit=AuditLog(self.root/'audit.sqlite3')
        self.assertTrue(self.audit.has_uncertain_submission())
        with self.assertRaises(PermissionError):self.reserve(self.proposal('must-not-send'),cash=True)
        self.assertIsNone(self.audit.get('must-not-send'))
        with closing(self.audit._connect()) as c:self.assertEqual(c.execute('SELECT state FROM entry_cash_claims').fetchone()[0],'UNKNOWN')

    def test_single_transport_latch_rejects_unsent_competitor_without_spending_budget(self):
        self.reserve(self.proposal('a'));self.reserve(self.proposal('b'))
        barrier=threading.Barrier(2)
        def start(key):barrier.wait();return self.audit.mark_submission_started(key)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(start,('a','b')))
        self.assertEqual(sorted(results),[False,True])
        statuses={x['status'] for x in self.audit.list_recent(10)}
        self.assertEqual(statuses,{'STARTED','REJECTED_NOT_SENT'})
        day=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
        self.assertEqual(self.audit.paper_notional_for_date(day,'America/New_York'),100)

    def test_rejected_callback_rolls_back_intent_and_claim(self):
        def reject(c,at):raise PermissionError('Revoked before reservation commit')
        with self.assertRaises(PermissionError):self.audit.reserve(self.proposal('revoked'),'PAPER_TRANSMIT','strategy',admission_check=reject)
        self.assertIsNone(self.audit.get('revoked'))

    def test_fx_funding_does_not_consume_stock_day_budget(self):
        self.audit.reserve(self.proposal('fx',100000),'PAPER_CASH_CONVERSION','scoped-cash')
        self.assertTrue(self.reserve(self.proposal('stock'),cap=100))

    def test_status_relabel_never_replays_a_started_occurrence(self):
        self.reserve(self.proposal('immutable-occurrence'))
        self.assertTrue(self.audit.mark_submission_started('immutable-occurrence'))
        self.audit.update('immutable-occurrence','RESERVED','A status label cannot erase history')
        with self.assertRaises(PermissionError):self.audit.mark_submission_started('immutable-occurrence')

    def test_active_fx_order_blocks_even_without_additive_limits(self):
        self.funding(10000)
        with closing(sqlite3.connect(self.runtime/'recovery.sqlite3')) as c,c:
            state=json.loads(c.execute('SELECT payload FROM paper_safety_state').fetchone()[0])
            state['orders']={'fx':{'account':'DUQ503649','symbol':'EUR','currency':'USD','sec_type':'CASH','con_id':12087792,'side':'SELL','order_type':'LMT','remaining':1,'limit_price':1.1,'status':'Submitted'}}
            c.execute('UPDATE paper_safety_state SET payload=?',(json.dumps(state),))
        with self.assertRaises(PermissionError):self.reserve(self.proposal('blocked-fx'),cash=True)
        self.assertIsNone(self.audit.get('blocked-fx'))

    def test_gate_revoked_during_preflight_rolls_back_before_transport(self):
        from unittest.mock import patch
        from tests.test_service import make_settings,valid_limit_payload
        from trading.service import TradingService
        service=TradingService(make_settings(str(self.root),trading_mode='PAPER',allow_paper_transmit=True,trade_session_token='session-ok',max_order_value=400))
        payload=valid_limit_payload('revoked-in-preflight');payload['trade_session_token']='session-ok'
        with patch.object(service,'_require_submission_allowed',side_effect=[None,PermissionError('Revoked during preflight')]),patch.object(service,'_tws_status',return_value={'ready_for_orders':True}),patch('trading.service.TwsPaperBroker') as broker:
            with self.assertRaisesRegex(PermissionError,'Revoked during preflight'):service.submit_limit(payload,transmit=True)
        broker.assert_not_called()
        self.assertIsNone(service._audit.get('revoked-in-preflight'))

    def test_risk_cap_changed_during_preflight_rejects_atomically(self):
        from unittest.mock import patch
        from tests.test_service import make_settings,valid_limit_payload
        from trading.service import TradingService
        from trading.models import RiskDecision
        service=TradingService(make_settings(str(self.root),trading_mode='PAPER',allow_paper_transmit=True,trade_session_token='session-ok',max_order_value=400))
        payload=valid_limit_payload('risk-revoked');payload['trade_session_token']='session-ok'
        with patch.object(service,'_require_submission_allowed'),patch.object(service,'_validate_risk',side_effect=[RiskDecision(True,'APPROVED','initial'),RiskDecision(False,'REJECTED','OMAX reduced')]),patch.object(service,'_tws_status',return_value={'ready_for_orders':True}),patch('trading.service.TwsPaperBroker') as broker:
            with self.assertRaisesRegex(PermissionError,'OMAX reduced'):service.submit_limit(payload,transmit=True)
        broker.assert_not_called();self.assertIsNone(service._audit.get('risk-revoked'))

    def native_parent(self,key='bound',**changes):
        return {'order_id':11,'perm_id':9911,'parent_id':0,'client_id':22,'order_ref':key,'account':'DUQ503649',
                'symbol':'BAC','side':'BUY','con_id':9029,'currency':'USD','sec_type':'STK','order_type':'LMT','quantity':1,
                'limit_price':100,'aux_price':0,'tif':'DAY','remaining':1,'filled':0,'status':'Submitted','transmit':True,**changes}

    def test_native_binding_keeps_exact_identity_and_status_updates_do_not_change_it(self):
        self.funding();p=self.proposal('bound');self.reserve(p,cash=True);self.audit.mark_submission_started('bound');self.audit.update('bound','PAPER_LIMIT_SUBMITTED','native ACK')
        parent=self.native_parent()
        self.assertTrue(self.audit.record_submission('bound',[11],{11:'Submitted'},broker_order_evidence={11:parent},expected_client_id=22))
        self.assertTrue(self.audit.record_submission('bound',[11],{11:'Filled'},broker_order_evidence={11:{**parent,'remaining':0,'filled':1,'status':'Filled'}},expected_client_id=22))
        with closing(self.audit._connect()) as c:
            binding=json.loads(c.execute('SELECT binding FROM entry_native_bindings').fetchone()[0])
        self.assertEqual(binding['parent']['perm_id'],9911);self.assertFalse(binding['mutation_authorized'])

    def test_forged_order_reference_without_native_scope_never_binds_claim(self):
        self.funding();p=self.proposal('forged');self.reserve(p,cash=True);self.audit.mark_submission_started('forged');self.audit.update('forged','PAPER_LIMIT_SUBMITTED','ACK')
        bad=self.native_parent('forged',client_id=0)
        self.assertFalse(self.audit.record_submission('forged',[11],{11:'Submitted'},broker_order_evidence={11:bad},expected_client_id=22))
        self.assertTrue(self.audit.has_uncertain_submission())
        with closing(self.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM entry_native_bindings').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT state FROM entry_cash_claims').fetchone()[0],'UNKNOWN')
            self.assertEqual(c.execute('SELECT count(*) FROM broker_orders').fetchone()[0],0)

    def cash_proof(self,parent,at,*,filled=1,remaining=0,status='Filled'):
        stamp=lambda offset:datetime.fromtimestamp(at+offset,timezone.utc).isoformat()
        return {'broker_state':{'identity':True,'connected':True,'upstream_connected':True,'dirty':False,'ends':['positions','orders','completed_orders','executions'],'last_server_reply':at+.9,'epoch':'new-reconciled-epoch','reconciled_at':at+1,'orders':{'native':{**parent,'filled':filled,'remaining':remaining,'status':status,'completed':status in ('Filled','Cancelled')}}},
                'cashbook':{'source':'BROKER_API','account':'DUQ503649','base_currency':'EUR','currency_coverage':'USD_AND_BASE_VERIFIED','requested_currencies':['USD','EUR'],
                    'cash_read_started_at':stamp(2),'cash_read_finished_at':stamp(3),'observed_at':stamp(3),'currencies':{'USD':{'amount':'899','currency':'USD'},'EUR':{'amount':'10000','currency':'EUR'}}}}

    def bound_cash(self):
        self.funding();p=self.proposal('accounting-bound');self.reserve(p,cash=True);self.audit.mark_submission_started(p.idempotency_key);self.audit.update(p.idempotency_key,'PAPER_LIMIT_SUBMITTED','native ACK')
        parent=self.native_parent(p.idempotency_key)
        self.audit.record_submission(p.idempotency_key,[11],{11:'Submitted'},broker_order_evidence={11:parent},expected_client_id=22)
        return p,parent,time.time()

    def test_cash_transfer_waits_for_exact_native_fill_and_actual_fee(self):
        from trading.entry_admission import reconcile_cash_claims
        p,parent,at=self.bound_cash();stamp=lambda offset:datetime.fromtimestamp(at+offset,timezone.utc).isoformat()
        execution=dict(exec_id='fill-accounting',account='DUQ503649',perm_id=parent['perm_id'],order_id=11,order_ref=p.idempotency_key,symbol='BAC',side='BOT',shares=1,price=100,time=stamp(.5),con_id=9029,sec_type='STK',currency='USD')
        with closing(self.audit._connect()) as c,c:self.audit._upsert_execution(c,execution,stamp(.5))
        context=self.cash_proof(parent,at)
        with closing(self.audit._connect()) as c,c:
            reconcile_cash_claims(c,context,stamp(4))
            self.assertEqual(c.execute('SELECT state,reserved_usd FROM entry_cash_claims').fetchone()[:],('BROKER_ACCOUNTED_FEE_HELD','5'))
        self.audit.record_execution_fee(execution['exec_id'],'USD',1,stamp(1.5),'commissionAndFeesReport')
        with closing(self.audit._connect()) as c,c:
            reconcile_cash_claims(c,context,stamp(4))
            self.assertEqual(c.execute('SELECT state,reserved_usd FROM entry_cash_claims').fetchone()[:],('RELEASED_TO_BROKER_CASHBOOK','0'))

    def test_orderref_match_without_exact_permid_and_stale_cash_cannot_release(self):
        from trading.entry_admission import reconcile_cash_claims
        p,parent,at=self.bound_cash();context=self.cash_proof(parent,at,filled=0,remaining=1,status='Submitted')
        context['broker_state']['orders']['native']['perm_id']=9912
        with closing(self.audit._connect()) as c,c:
            reconcile_cash_claims(c,context,datetime.now(timezone.utc).isoformat())
            self.assertEqual(c.execute('SELECT reserved_usd FROM entry_cash_claims').fetchone()[0],'105')
        context['broker_state']['orders']['native']=parent
        context['cashbook']['cash_read_started_at']=datetime.fromtimestamp(at-1,timezone.utc).isoformat()
        with closing(self.audit._connect()) as c,c:
            reconcile_cash_claims(c,context,datetime.now(timezone.utc).isoformat())
            self.assertEqual(c.execute('SELECT reserved_usd FROM entry_cash_claims').fetchone()[0],'105')

    def test_funded_strategy_cannot_bypass_linked_protection_through_limit_route(self):
        from unittest.mock import patch
        from tests.test_service import make_settings,valid_limit_payload
        from trading.service import TradingService
        self.funding()
        service=TradingService(make_settings(str(self.root),trading_mode='PAPER',allow_paper_transmit=True,trade_session_token='session-ok',max_order_value=400))
        payload=valid_limit_payload('no-unprotected-entry');payload['trade_session_token']='session-ok'
        with patch('trading.production_paths.STATE_ROOT',self.root),patch.object(service,'_tws_status',return_value={'ready_for_orders':True}),patch('trading.service.TwsPaperBroker') as broker:
            with self.assertRaisesRegex(PermissionError,'Linked native protective entry required'):service.submit_limit(payload,transmit=True)
        broker.assert_not_called();self.assertIsNone(service._audit.get(payload['idempotency_key']))

    def test_correction_family_cannot_release_cash_even_when_summed_quantity_looks_valid(self):
        from trading.entry_admission import reconcile_cash_claims
        p,parent,at=self.bound_cash();stamp=lambda offset:datetime.fromtimestamp(at+offset,timezone.utc).isoformat()
        with closing(self.audit._connect()) as c,c:
            for identity,shares in (('corrected.fill.01',.4),('corrected.fill.02',.6)):
                execution=dict(exec_id=identity,account='DUQ503649',perm_id=parent['perm_id'],order_id=11,order_ref=p.idempotency_key,symbol='BAC',side='BOT',shares=shares,price=100,time=stamp(.5),con_id=9029,sec_type='STK',currency='USD')
                self.audit._upsert_execution(c,execution,stamp(.5))
            reconcile_cash_claims(c,self.cash_proof(parent,at),stamp(4))
            self.assertEqual(c.execute('SELECT state,reserved_usd FROM entry_cash_claims').fetchone()[:],('ACKNOWLEDGED_UNRECONCILED','105'))
