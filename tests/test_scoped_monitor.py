from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import json,tempfile,unittest
from unittest.mock import patch,Mock
from trading.paper_safety_monitor import PaperSafetyMonitor,ACCOUNT,ENDS
from trading.paper_safety_client import PaperSafetyClient
from trading.paper_strategy_observer import PaperStrategyObserver
from trading.symbol_health import SYSTEMIC_PAUSE_FACTS

class ScopedMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=1000
        session=patch('trading.paper_safety_monitor.session_for_symbol',return_value='REGULAR');session.start();self.addCleanup(session.stop)
        self.deps={'classic_conservative_trend':{'A':['A'],'B':['B']},'pair':{'A':['A','B']}}
        self.m=PaperSafetyMonitor(self.root/'audit.db',self.root/'recovery.db',symbols=['A','B'],required_bars=1,
            clock=lambda:self.now,strategy_dependencies=self.deps,system_safety={k:True for k in SYSTEMIC_PAUSE_FACTS})
        self.m.begin([ACCOUNT])
        self.m.position('B',1,con_id=42,currency='USD',sec_type='STK')
        self.m.order(dict(order_id=77,perm_id=912,account=ACCOUNT,symbol='B',side='SELL',order_type='STP',
            status='PreSubmitted',quantity=1,remaining=1,filled=0,transmit=True,parent_id=0,
            con_id=42,currency='USD',sec_type='STK',aux_price=19))
        for end in ENDS:self.m.end(end)
    def warm(self):
        self.now=1200
        for end in ENDS:self.m.end(end)
        for symbol in ('A','B'):
            self.m.state['market_types'][symbol]=1
            self.m.bar(symbol,1140,1200)
        for step in range(3):
            self.now=1200+step
            for symbol in ('A','B'):self.m.quote(symbol,20,20.01,self.now,self.now,1)
            self.m.poll_symbol_recovery()
        self.m._publish()
    def events(self):
        with closing(self.m.coordinator.connect()) as c:
            return [json.loads(p) for p, in c.execute("SELECT payload FROM paper_callback_events WHERE kind='pause_transition' ORDER BY observed,event_id")]
    def test_real_monitor_10197_is_local_and_never_cancels_protection(self):
        self.warm();self.assertTrue(self.m.snapshot()['pause_scopes']['decisions']['classic_conservative_trend']['A']['allowed'])
        before_orders=dict(self.m.state['orders']);self.assertEqual(len(before_orders),1)
        with patch('trading.tws_paper.TwsPaperBroker') as broker:
            self.m.market_error('B',10197,'competing session');self.m.error(10197,symbol='B')
        policy=self.m.snapshot()['pause_scopes']
        self.assertFalse(policy['global_new_orders_paused'])
        self.assertTrue(policy['decisions']['classic_conservative_trend']['A']['allowed'])
        self.assertFalse(policy['decisions']['classic_conservative_trend']['B']['allowed'])
        self.assertFalse(policy['decisions']['pair']['A']['allowed'])
        self.assertEqual(before_orders,self.m.state['orders']);broker.assert_not_called()
        before=len(self.events());self.m._publish();self.m._publish();self.assertEqual(len(self.events()),before)
        self.assertTrue(any(e['action']=='PAUSE' and 'B' in e['affected_symbols'] for e in self.events()))
        self.m.invalidate('IDENTITY_MISMATCH');self.assertTrue(self.m.snapshot()['pause_scopes']['global_new_orders_paused'])
    def test_history_end_proves_kline_without_five_second_callbacks(self):
        self.warm();self.m.state['bars'].clear()
        observer=PaperStrategyObserver(['A','B'],dict(fast_window=2,slow_window=3),self.root/'observer.json')
        client=PaperSafetyClient(self.m,['A','B']);client.strategy_observer=observer
        client.reqMktData=Mock();client.reqRealTimeBars=Mock()
        client.historicalData(49000,SimpleNamespace(date='1140',open=20,high=20,low=20,close=20,volume=1))
        self.assertFalse(self.m.snapshot()['pause_scopes']['decisions']['classic_conservative_trend']['A']['allowed'])
        client.historicalDataEnd(49000,'','')
        self.assertTrue(self.m.snapshot()['pause_scopes']['decisions']['classic_conservative_trend']['A']['allowed'])
        self.assertEqual(self.m.state['bars'],{})
        client.reqMktData.assert_not_called();client.reqRealTimeBars.assert_not_called()
    def test_recovery_transition_never_reports_resume_before_risk_verified(self):
        self.warm();self.m.error(10197,symbol='B')
        self.m.system_safety['global_risk_verified']=False
        self.now=1320
        for end in ENDS:self.m.end(end)
        for symbol in ('A','B'):
            self.m.state['market_types'][symbol]=1;self.m.bar(symbol,1260,1320)
        count=len(self.events())
        for step in range(3):
            self.now=1320+step
            for symbol in ('A','B'):self.m.quote(symbol,20,20.01,self.now,self.now,1)
            self.m.poll_symbol_recovery()
        self.m._publish()
        self.assertFalse(any(e['action']=='RESUME' for e in self.events()[count:]))
        self.m.system_safety['global_risk_verified']=True;self.m._publish()
        self.assertTrue(self.m.snapshot()['pause_scopes']['decisions']['classic_conservative_trend']['B']['allowed'])
        self.assertTrue(any(e['action']=='RESUME' and 'B' in e['affected_symbols'] for e in self.events()))
