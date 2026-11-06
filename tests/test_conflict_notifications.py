from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from trading.subscription_lifecycle import SubscriptionLifecycle
from trading.symbol_health import SymbolRecovery
from trading.paper_safety_monitor import PaperSafetyMonitor, ACCOUNT
from trading.paper_safety_client import PaperSafetyClient
from reporting.incident_mail import message_for

class ConflictTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.p=Path(self.tmp.name)/'r.db';self.now=1000
  self.r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
 def queue(self):
  with closing(self.r.store.connect()) as c:
   return c.execute("select kind,payload from notification_outbox where incident_key='market-session-conflict:PFE' order by id").fetchall()
 def fields(self):return dict(data_type=1,bid=20,ask=20.01,bid_at=self.now,ask_at=self.now)
 def recover(self,reconciled=True,session='REGULAR'):
  for i in range(3):
   self.now+=1;self.r.observe('PFE',self.fields(),session=session,reconciliation_verified=reconciled)
 def test_first_duplicate_restart_recovery_and_second_episode(self):
  self.r.error('PFE',10197,'competing');self.assertEqual([k for k,p in self.queue()],['ALERT'])
  self.r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
  self.r.error('PFE',10197,'duplicate');self.assertEqual(len(self.queue()),1)
  self.recover();self.assertEqual([k for k,p in self.queue()],['ALERT','RECOVERY'])
  self.r.error('PFE',10197,'new conflict');self.recover()
  self.assertEqual([k for k,p in self.queue()],['ALERT','RECOVERY','ALERT','RECOVERY'])
 def test_clearance_requires_new_live_quotes_and_reconciliation_not_calendar(self):
  old=self.fields()
  self.r.error('PFE',10197,'competing');self.recover(False)
  self.assertEqual(len(self.queue()),1)
  for i in range(4):self.r.observe('PFE',old,session='CLOSED',reconciliation_verified=True)
  self.assertEqual(len(self.queue()),1)
  self.now+=1
  self.r.observe('PFE',self.fields(),session='CLOSED',reconciliation_verified=True)
  self.assertEqual(len(self.queue()),2)
  for i in range(4):self.r.observe('PFE',self.fields(),session='CLOSED',reconciliation_verified=True)
  self.assertEqual(len(self.queue()),2)
  self.assertFalse(self.r.snapshot('PFE')['health']['allows_realtime'])
 def test_restart_old_state_does_not_manufacture_a_conflict(self):
  self.r.lifecycle.seed_legacy('PFE',4,'old');self.recover()
  self.assertEqual(self.queue(),[])
 def exhaust(self):
  self.r.error('PFE',10197,'competing')
  for i in range(4):
   self.now+=300;g=self.r.lifecycle.reserve('PFE',('quotes',),str(i),reason='RECOVERY')
   self.assertTrue(g['allowed']);self.r.lifecycle.finish(g,sent=True)
 def test_low_frequency_is_atomic_spaced_and_persistent(self):
  self.exhaust();self.now+=899
  self.assertFalse(self.r.lifecycle.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY')['allowed'])
  self.now+=1;g=self.r.lifecycle.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY');self.assertTrue(g['allowed'])
  other=SubscriptionLifecycle(self.p,clock=lambda:self.now)
  self.assertFalse(other.reserve('PFE',('quotes',),'peer',reason='LOW_FREQUENCY_RECOVERY')['allowed'])
  self.r.lifecycle.finish(g,sent=True);self.assertEqual(other.snapshot('PFE')['attempts'],4)
  self.now+=899;self.assertFalse(other.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY')['allowed'])
  self.now+=1;self.assertTrue(other.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY')['allowed'])
 def test_low_frequency_respects_unknown_and_permission_and_closed(self):
  self.exhaust();self.now+=900
  self.r.error('PFE',354,'permission');self.assertIsNone(self.r.retry_due('PFE',session='REGULAR',connected=True))
  self.r.error('PFE',10197,'still competing');self.assertIsNone(self.r.retry_due('PFE',session='CLOSED',connected=True))
  self.assertIsNone(self.r.retry_due('PFE',session='REGULAR',connected=False))
  g=self.r.lifecycle.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY');self.r.lifecycle.finish(g,sent=False)
  self.now+=10000;self.assertIsNone(self.r.retry_due('PFE',session='REGULAR',connected=True))
 def test_poll_admits_existing_owner_without_order_methods(self):
  self.exhaust();self.now+=900
  a=self.r.retry_due('PFE',session='REGULAR',connected=True)
  self.assertTrue(a['low_frequency']);self.assertEqual(a['symbols'],['PFE'])
  m=PaperSafetyMonitor(self.p.parent/'audit.db',self.p,symbols=['PFE'],required_bars=1,clock=lambda:self.now)
  c=PaperSafetyClient(m,['PFE'])
  for method in ('reqMarketDataType','reqMktData','reqRealTimeBars','cancelMktData','cancelRealTimeBars'):
   setattr(c,method,Mock())
  c.placeOrder=Mock(side_effect=AssertionError('no orders'));c.cancelOrder=Mock(side_effect=AssertionError('no cancel'))
  g=c.retry_symbol_subscriptions(a['symbols'],low_frequency=True)[0];self.assertTrue(g['allowed'])
  c.reqMktData.assert_called_once();c.placeOrder.assert_not_called();c.cancelOrder.assert_not_called()
 def test_mail_has_code_and_no_claim_of_phone_logout_or_trade_ready(self):
  self.r.error('PFE',10197,'competing')
  item=self.r.store.claim();mail=message_for(item,'fixture@example.invalid','PAUSED')
  self.assertIn('10197',mail.get_content());self.assertIn('not verified',mail.get_content())

 def test_concurrent_slow_probe_and_new_episode_spacing(self):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  self.exhaust();self.now+=900;b=Barrier(2)
  def reserve(i):
   l=SubscriptionLifecycle(self.p,clock=lambda:self.now);b.wait(timeout=3)
   return l.reserve('PFE',('quotes',),str(i),reason='LOW_FREQUENCY_RECOVERY')
  with ThreadPoolExecutor(max_workers=2) as pool:grants=list(pool.map(reserve,range(2)))
  self.assertEqual(sum(g['allowed'] for g in grants),1)
  self.r.lifecycle.finish(next(g for g in grants if g['allowed']),sent=True)
  self.recover();self.r.verified_recovery('PFE')
  self.exhaust();self.now+=899
  self.assertFalse(self.r.lifecycle.reserve('PFE',('quotes',),'new',reason='LOW_FREQUENCY_RECOVERY')['allowed'])

 def test_monitor_only_passes_recent_complete_reconciliation_to_notices(self):
  m=PaperSafetyMonitor(self.p.parent/'a.db',self.p,symbols=['PFE'],required_bars=1,clock=lambda:self.now)
  m.begin([ACCOUNT]);m.state.update(upstream_connected=True,dirty=False,ends=['positions','orders','completed_orders','executions'],last_server_reply=self.now,reconciled_at=self.now-31)
  m.symbol_recovery.error('PFE',10197,'competing')
  from unittest.mock import patch
  with patch('trading.paper_safety_monitor.session_for_symbol',return_value='REGULAR'):
   for _ in range(3):
    self.now+=1;m.state['last_server_reply']=self.now;m.state['quotes']['PFE']=self.fields();m.state['market_types']['PFE']=1;m.poll_symbol_recovery()
   self.assertEqual(len(self.queue()),1)
   for _ in range(3):
    self.now+=1;m.state.update(last_server_reply=self.now,reconciled_at=self.now);m.state['quotes']['PFE']=self.fields();m.poll_symbol_recovery()
   self.assertEqual([k for k,p in self.queue()],['ALERT','RECOVERY'])

 def test_reconnect_incident_followed_by_conflict_still_probes(self):
  self.r.lifecycle.open_fault('PFE','RECONNECT')
  self.exhaust();self.now+=900
  self.assertEqual(self.r.lifecycle.snapshot('PFE')['cause'],'RECONNECT')
  a=self.r.retry_due('PFE',session='REGULAR',connected=True)
  self.assertTrue(a['low_frequency'])
  self.assertTrue(self.r.lifecycle.reserve('PFE',('quotes',),'c',reason='LOW_FREQUENCY_RECOVERY')['allowed'])
