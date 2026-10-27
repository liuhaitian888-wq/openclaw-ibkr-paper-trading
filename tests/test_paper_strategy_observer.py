import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace as NS
from trading.paper_strategy_observer import PaperStrategyObserver

class StrategyObserverTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.o=PaperStrategyObserver(['BAC'],dict(fast_window=2,slow_window=3,stop_loss_pct=0.0015,profit_target_pct=0.0015,min_gap_pct=0.0001,cooldown_steps=0),Path(self.tmp.name)/'latest.json')
 def raw(self,t,p):return NS(date=str(t),open=p,high=p,low=p,close=p,volume=100)
 @patch('trading.market_data.Quote.age_ms',return_value=0)
 def test_original_strategy_risk_and_native_proposal_without_transmission(self,age):
  for t,p in ((600,49),(660,50),(720,51)):self.assertTrue(self.o.history('BAC',self.raw(t,p),780))
  self.o.history_complete.add('BAC')
  r=self.o.evaluate('BAC',dict(bid=51.00,ask=51.01,bid_at=780,ask_at=780,data_type=1),dict(entries_ready=True),780)
  self.assertEqual(r['signal']['action'],'BUY');self.assertTrue(r['risk_engine']['approved'])
  self.assertEqual(r['proposed_native_protection']['parent']['tif'],'DAY')
  self.assertEqual(r['proposed_native_protection']['child']['tif'],'GTC')
  self.assertFalse(r['transmit']);self.assertFalse(r['eligible_to_submit'])
  self.assertEqual(self.o.config.stop_loss_pct,0.0015)
 def test_incomplete_future_stale_and_crossed_data_block(self):
  self.assertFalse(self.o.history('BAC',self.raw(780,51),800))
  self.assertEqual(self.o.bars['BAC'],{})
  self.assertFalse(self.o.history('BAC',self.raw(900,51),800))
  for t in (600,660,720):self.o.history('BAC',self.raw(t,50),780)
  self.o.history_complete.add('BAC')
  r=self.o.evaluate('BAC',dict(bid=51,ask=50,bid_at=780,ask_at=780,data_type=1),dict(entries_ready=False),780)
  self.assertEqual(r['status'],'BLOCKED')
  r=self.o.evaluate('BAC',dict(bid=50,ask=51,bid_at=1000,ask_at=1000,data_type=1),dict(entries_ready=False),1000)
  self.assertEqual(r['status'],'BLOCKED')
 def test_pending_bar_only_closes_after_next_minute(self):
  self.o.history('BAC',self.raw(780,50),800)
  self.o.history('BAC',self.raw(840,51),845)
  self.assertIn(780,self.o.bars['BAC']);self.assertNotIn(840,self.o.bars['BAC'])
