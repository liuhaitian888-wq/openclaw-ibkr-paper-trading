from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import tempfile
import unittest
from trading.paper_safety_client import PaperSafetyClient
from trading.paper_safety_monitor import PaperSafetyMonitor
from trading.paper_strategy_observer import PaperStrategyObserver

class HistoryRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=1020
  self.m=PaperSafetyMonitor(self.root/'a.db',self.root/'r.db',symbols=['BAC'],required_bars=3,clock=lambda:self.now)
  self.m.state['upstream_connected']=True
  self.o=PaperStrategyObserver(['BAC'],dict(fast_window=2,slow_window=3),self.root/'o.json')
  self.c=PaperSafetyClient(self.m,['BAC']);self.c.strategy_observer=self.o
  for name in ('reqHistoricalData','cancelHistoricalData','reqMktData','cancelMktData','reqRealTimeBars','cancelRealTimeBars'):
   setattr(self.c,name,Mock())
 def bar(self,t):return NS(date=str(t),open=1,high=1,low=1,close=1,volume=1)
 def test_gap_backfill_uses_history_only_and_closes_only_from_actual_bars(self):
  for t in (780,900):self.o.history('BAC',self.bar(t),self.now)
  self.assertEqual(self.o.history_gaps('BAC',self.now),[840])
  self.m.state['bars']['BAC']=[960];self.c.bar_parts['BAC']={960:{960}}
  self.c.historicalDataEnd(49000,'','');self.c.backfill_history_gaps()
  self.c.reqHistoricalData.assert_called_once()
  self.c.reqMktData.assert_not_called();self.c.reqRealTimeBars.assert_not_called()
  self.assertEqual(self.m.state['bars']['BAC'],[960]);self.assertIn('BAC',self.c.bar_parts)
  self.assertNotIn(840,self.o.bars['BAC'])
  self.c.historicalData(49000,self.bar(840));self.c.historicalDataEnd(49000,'','')
  self.assertEqual(self.o.history_gaps('BAC',self.now),[])
  self.assertEqual(self.c.backfill_history_gaps(),[])
 def test_unfilled_gap_shares_four_attempt_budget_and_waits_upstream(self):
  for t in (780,900):self.o.history('BAC',self.bar(t),self.now)
  self.c.historicalDataEnd(49000,'','');self.m.state['upstream_connected']=False
  self.assertEqual(self.c.backfill_history_gaps(),[])
  self.m.state['upstream_connected']=True
  for _ in range(4):self.c.backfill_history_gaps();self.now+=30
  # All gap batches share the same four-attempt ceiling.
  for _ in range(5):self.now+=300;self.c.backfill_history_gaps()
  self.assertLessEqual(self.c.reqHistoricalData.call_count,4)
  self.assertEqual(self.o.history_gaps('BAC',1020),[840])
