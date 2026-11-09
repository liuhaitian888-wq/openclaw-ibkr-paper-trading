from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from reporting.paper_readiness import collect,inventory,message

class PaperReadinessTests(unittest.TestCase):
    def state(self):
        contract={'con_id':1,'currency':'USD','sec_type':'STK'}
        return {'identity':True,'connected':True,'upstream_connected':True,'dirty':False,'last_server_reply':100,
            'ends':['positions','orders','completed_orders','executions'],'positions':{'PFE':8,'AAPL':17,'NVDA':0},
            'contracts':{'PFE':contract},'orders':{'1':{**contract,'symbol':'PFE','account':'DUQ503649','side':'SELL','order_type':'STP','status':'PreSubmitted','transmit':True,'perm_id':123,'remaining':8,'aux_price':23.01,'parent_id':0}}}
    def root(self,tmp,state):
        r=Path(tmp);(r/'runtime').mkdir();(r/'production.json').write_text(json.dumps({'ready':False,'strategy_configuration':{'execution_approved':False}}));(r/'PAUSED').touch()
        with closing(sqlite3.connect(r/'runtime/recovery.sqlite3')) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)');c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(state),))
            c.execute('CREATE TABLE operation_attempts(kind TEXT,status TEXT)')
        with closing(sqlite3.connect(r/'trading_audit.sqlite3')) as c,c:c.execute('CREATE TABLE order_requests(status TEXT)')
        return r
    def test_fresh_broker_facts_never_clear_execution_approval_or_adopt_holdings(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,self.state());before=(r/'production.json').read_bytes();d=collect(r,now=101)
            self.assertTrue(d['broker_state_verified']);self.assertFalse(d['automatic_trading_ready']);self.assertFalse(d['grants_trading_permission'])
            self.assertEqual([(x['symbol'],x['protection']) for x in d['holdings']],[('AAPL','UNPROTECTED'),('PFE','PROTECTED')])
            self.assertTrue((r/'PAUSED').exists());self.assertEqual((r/'production.json').read_bytes(),before)
            self.assertNotIn('NVDA',message(d,holdings_only=True));self.assertIn('MANIFEST_EXECUTION · BLOCKED',message(d))
    def test_incomplete_and_stale_readback_cannot_claim_current_protection(self):
        for changes in ({'ends':['positions']},{'last_server_reply':10},{'dirty':True},{'identity':False},{'upstream_connected':False}):
            with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
                d=collect(self.root(tmp,{**self.state(),**changes}),now=101)
                self.assertFalse(d['broker_state_verified']);self.assertTrue(all(x['protection']=='STALE_OR_UNVERIFIED' for x in d['holdings']))
    def test_wrong_account_or_duplicate_stop_never_counts_as_verified_coverage(self):
        s=self.state();s['orders']['1']['account']='OTHER'
        self.assertNotEqual(inventory(s,verified=True)[1]['protection'],'PROTECTED')
        s=self.state();s['orders']['2']=s['orders']['1'].copy()
        self.assertNotEqual(inventory(s,verified=True)[1]['protection'],'PROTECTED')
    def test_missing_or_unreadable_ledgers_are_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,self.state());(r/'trading_audit.sqlite3').unlink();d=collect(r,now=101)
            gate=next(x for x in d['checks'] if x['gate']=='NO_UNCERTAIN_ORDERS')
            self.assertEqual(gate['state'],'BLOCKED');self.assertIsNone(gate['detail']['pending_order_requests']);self.assertFalse((r/'trading_audit.sqlite3').exists())
    def test_corrupt_required_controls_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,self.state());(r/'runtime/RISK_CONTROLS_REQUIRED').touch();(r/'runtime/risk-controls.json').write_text('{')
            d=collect(r,now=101);self.assertIsNone(d['risk_controls']);self.assertIn('risk_controls',d['unavailable_evidence'])

    def test_fx_pair_and_actual_funding_remain_separate(self):
        s=self.state();s['positions']['EUR']=-64414;s['contracts']['EUR']={'con_id':12087792,'currency':'USD','sec_type':'CASH'}
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,s);d=collect(r,now=101)
            self.assertNotIn('EUR',[x['symbol'] for x in d['holdings']])
            self.assertEqual(d['portfolio']['fx_pair_positions'][0]['quantity'],-64414)
            self.assertIn('非现金余额',message(d,holdings_only=True))
            self.assertEqual(next(x for x in d['checks'] if x['gate']=='USD_CASH_AVAILABLE')['state'],'BLOCKED')
            self.assertFalse(d['automatic_trading_ready']);self.assertTrue((r/'PAUSED').exists())

    def test_positive_cash_without_native_settlement_cannot_pass_funding_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,self.state())
            (r/'runtime/currency-book.latest.json').write_text(json.dumps({'source':'BROKER_API','account':'DUQ503649','observed_at':'1970-01-01T00:01:40+00:00','currencies':{'USD':{'amount':'2019.4231','currency':'USD'}}}))
            d=collect(r,now=101);checks={x['gate']:x for x in d['checks']}
            self.assertEqual(checks['USD_CASH_AVAILABLE']['state'],'PASS')
            self.assertEqual(checks['SETTLED_USD_EVIDENCE']['state'],'BLOCKED')
            self.assertFalse(d['automatic_trading_ready'])

    def test_settlement_receipt_does_not_hide_missing_actual_usd_cash(self):
        from tests.test_settlement_book import SettlementBookTests
        with tempfile.TemporaryDirectory() as tmp:
            r=self.root(tmp,self.state());receipt=SettlementBookTests().receipt()
            receipt['values'][1]['value']='20261109:2019.42306'
            (r/'runtime/currency-book.latest.json').write_text(json.dumps({'source':'BROKER_API','account':'DUQ503649','base_currency':'EUR','observed_at':'2026-11-09T20:42:01+00:00','currencies':{},'settlement_receipt':receipt}))
            d=collect(r,now=1794256922);checks={x['gate']:x for x in d['checks']}
            self.assertEqual(checks['SETTLED_USD_EVIDENCE']['state'],'BLOCKED')
