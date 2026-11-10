from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from trading.subscription_lifecycle import SubscriptionLifecycle
from trading.paper_safety_monitor import PaperSafetyMonitor
from trading.paper_safety_client import PaperSafetyClient

class SubscriptionLifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.now=1000
  self.l=SubscriptionLifecycle(self.root/'r.db',clock=lambda:self.now)
 def reserve(self,connection='c',reason='INITIAL',symbol='PFE'):
  return self.l.reserve(symbol,('quotes','bars'),connection,reason=reason)
 def test_normal_first_and_duplicate_initial(self):
  g=self.reserve();self.assertTrue(g['allowed']);self.assertTrue(g['initial']);self.l.finish(g,sent=True)
  self.assertFalse(self.reserve()['allowed']);self.assertEqual(self.l.snapshot('PFE')['attempts'],0)
 def test_10197_reconnect_and_process_restart_share_four_attempts(self):
  g=self.reserve();self.l.finish(g,sent=True);self.l.open_fault('PFE','10197')
  for n in range(4):
   self.now+=300;self.l=SubscriptionLifecycle(self.root/'r.db',clock=lambda:self.now)
   self.l.open_fault('PFE','10197')
   g=self.reserve(connection=f'reconnect{n}');self.assertTrue(g['allowed']);self.assertEqual(g['attempt'],n+1)
   self.l.finish(g,sent=True)
   duplicate=self.reserve(connection=f'reconnect{n}');self.assertFalse(duplicate['allowed'])
  self.now+=10000
  self.assertEqual(self.reserve('new-process')['reason'],'INCIDENT_BUDGET_EXHAUSTED')
  self.assertFalse(self.reserve('new-process',reason='RECOVERY')['allowed'])
 def test_crash_after_reservation_and_unknown_send_do_not_replay(self):
  g=self.reserve();self.l=SubscriptionLifecycle(self.root/'r.db',clock=lambda:self.now)
  self.assertEqual(self.reserve('new')['reason'],'PENDING_OR_UNKNOWN_REQUEST')
  self.l.finish(g,sent=False);self.assertFalse(self.reserve('new')['allowed'])
  self.assertFalse(self.l.validated('PFE'))
 def test_budget_and_backoff_apply_to_direct_recovery_as_well(self):
  g=self.reserve();self.l.finish(g,sent=True)
  g=self.reserve(reason='RECOVERY');self.assertTrue(g['allowed']);self.l.finish(g,sent=True)
  self.assertEqual(self.reserve('next')['reason'],'INCIDENT_BACKOFF')
  self.now+=30;g=self.reserve('next');self.assertTrue(g['allowed']);self.l.finish(g,sent=True)
 def test_legacy_budget_is_not_replenished_by_deployment(self):
  self.l.seed_legacy('PFE',30,'legacy1')
  self.assertEqual(self.reserve()['reason'],'INCIDENT_BUDGET_EXHAUSTED')
  self.l.seed_legacy('PFE',0,'legacy1');self.assertFalse(self.reserve()['allowed'])
  self.assertTrue(self.reserve(symbol='BAC')['allowed'])
 def test_adapter_all_subscription_paths_use_same_budget_no_orders(self):
  m=PaperSafetyMonitor(self.root/'audit.db',self.root/'policy.db',symbols=['PFE'],required_bars=1,clock=lambda:self.now)
  def client():
   c=PaperSafetyClient(m,['PFE'])
   for name in ('reqMarketDataType','reqMktData','reqRealTimeBars','cancelMktData','cancelRealTimeBars'):
    setattr(c,name,Mock())
   c.placeOrder=Mock(side_effect=AssertionError('Forbidden order'));c.cancelOrder=Mock(side_effect=AssertionError('Forbidden cancel'))
   return c
  c=client();c.subscribe();c.subscribe();self.assertEqual(c.reqMktData.call_count,1)
  c.cancelMktData.assert_not_called()
  m.market_error('PFE',10197,'competing session')
  for n in range(4):
   self.now+=300;c=client();g=c.subscribe()[0];self.assertTrue(g['allowed']);c.cancelMktData.assert_not_called()
  self.now+=10000;c=client();self.assertFalse(c.subscribe()[0]['allowed'])
  c.retry_symbol_subscriptions(['PFE']);c.retry_subscriptions()
  c.reqMktData.assert_not_called();c.reqRealTimeBars.assert_not_called();c.cancelMktData.assert_not_called()
  c.placeOrder.assert_not_called();c.cancelOrder.assert_not_called()
 def test_existing_pfe_and_kill_switch_survive_admitted_recovery(self):
  m=PaperSafetyMonitor(self.root/'audit.db',self.root/'policy.db',symbols=['PFE'],required_bars=1,clock=lambda:self.now)
  stop=dict(symbol='PFE',remaining=8,aux_price=23.01,status='PreSubmitted',perm_id=911411084)
  m.state['orders']={'1':dict(stop)}
  with patch.dict(os.environ,{'TRADING_KILL_SWITCH':'true','ALLOW_PAPER_TRANSMIT':'false'}):
   c=PaperSafetyClient(m,['PFE'])
   for name in ('reqMarketDataType','reqMktData','reqRealTimeBars','cancelMktData','cancelRealTimeBars'):
    setattr(c,name,Mock())
   c.placeOrder=Mock(side_effect=AssertionError('Forbidden'));c.cancelOrder=Mock(side_effect=AssertionError('Forbidden'))
   c.subscribe();m.market_error('PFE',10197,'competing');self.now+=30;c.retry_subscriptions()
   self.assertEqual(m.state['orders'],{'1':stop});self.assertEqual(os.environ['TRADING_KILL_SWITCH'],'true');self.assertEqual(os.environ['ALLOW_PAPER_TRANSMIT'],'false')
   c.placeOrder.assert_not_called();c.cancelOrder.assert_not_called()

 def test_reusing_client_object_cannot_bypass_budget(self):
  m=PaperSafetyMonitor(self.root/'audit.db',self.root/'policy.db',symbols=['PFE'],required_bars=1,clock=lambda:self.now)
  c=PaperSafetyClient(m,['PFE'])
  for name in ('reqMarketDataType','reqMktData','reqRealTimeBars','cancelMktData','cancelRealTimeBars'):
   setattr(c,name,Mock())
  with patch('ibapi.client.EClient.connect'),patch.object(c,'isConnected',return_value=False):
   c.connect('127.0.0.1',4002,clientId=18770);self.assertTrue(c.subscribe()[0]['allowed'])
   m.market_error('PFE',10197,'competing')
   for _ in range(4):
    self.now+=300;c.connect('127.0.0.1',4002,clientId=18770);self.assertTrue(c.subscribe()[0]['allowed'])
   self.now+=300;c.connect('127.0.0.1',4002,clientId=18770)
   self.assertFalse(c.subscribe()[0]['allowed'])
