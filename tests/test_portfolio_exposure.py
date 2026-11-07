from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from trading.portfolio_exposure import measured_exposure

class PortfolioExposureTests(unittest.TestCase):
    def state(self):
        return {'identity':True,'connected':True,'upstream_connected':True,'dirty':False,'last_server_reply':100,
            'ends':['positions','orders','completed_orders','executions'],'positions':{'AAPL':17,'META':100},
            'contracts':{s:{'con_id':i+1,'currency':'USD','sec_type':'STK'} for i,s in enumerate(['AAPL','META'])},
            'quotes':{s:{'bid':99,'ask':100,'bid_at':100,'ask_at':100,'data_type':1} for s in ['AAPL','META']},'orders':{}}
    def measure(self,s):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'runtime';p.mkdir()
            with closing(sqlite3.connect(p/'recovery.sqlite3')) as c,c:
                c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)');c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(s),))
            return measured_exposure(Path(tmp),'AAPL',now=101)
    def test_external_holdings_and_buy_orders_remain_in_risk(self):
        s=self.state();s['orders']={'1':{'account':'DUQ503649','symbol':'META','currency':'USD','sec_type':'STK','side':'BUY','order_type':'LMT','remaining':2,'limit_price':110,'status':'Submitted'}}
        self.assertEqual(self.measure(s),(1700,11920))
    def test_missing_mark_and_incomplete_identity_fail_closed(self):
        for mutate in (lambda s:s['quotes'].pop('META'),lambda s:s.update(identity=False),lambda s:s.update(last_server_reply=1),lambda s:s['quotes']['AAPL'].update(data_type=3)):
            with self.subTest(mutate=mutate):
                s=self.state();mutate(s)
                with self.assertRaises(PermissionError):self.measure(s)
    def test_external_sells_do_not_reduce_reserved_risk_or_allow_unbounded_short(self):
        s=self.state();s['orders']={'1':{'account':'DUQ503649','symbol':'AAPL','currency':'USD','sec_type':'STK','side':'SELL','remaining':17,'status':'PreSubmitted'}}
        self.assertEqual(self.measure(s),(1700,11700));s['orders']['2']=s['orders']['1'].copy()
        with self.assertRaises(PermissionError):self.measure(s)
    def test_actual_service_passes_measured_exposure_to_risk_engine(self):
        from trading.service import TradingService
        from trading.risk import RiskLimits,RiskEngine
        from trading.models import TradeProposal
        service=object.__new__(TradingService);service._risk=RiskEngine(RiskLimits(True,frozenset({'AAPL'}),1,200,10))
        caps={'settings':{'max_symbol_exposure':'2000','max_gross_exposure':'2000'}}
        with patch('reporting.telegram_gate.current',return_value=caps),patch('trading.portfolio_exposure.measured_exposure',return_value=(1900,1900)),patch.object(service._risk,'validate',return_value='verified') as validate:
            proposal=TradeProposal('AAPL','BUY',1,100,95)
            self.assertEqual(service._validate_risk(proposal),'verified');validate.assert_called_once_with(proposal,current_symbol_exposure=1900,current_gross_exposure=1900)
