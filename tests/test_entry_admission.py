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
        (self.runtime/'currency-book.latest.json').write_text(json.dumps({'source':'BROKER_API','account':'DUQ503649','observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'currencies':{'USD':{'amount':str(cash)}}}))
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
