from pathlib import Path
import tempfile
import unittest
from trading.subscription_lifecycle import SubscriptionLifecycle
from trading.symbol_health import SymbolRecovery

class RearmTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)/'r.db';self.now=1000
  self.l=SubscriptionLifecycle(self.p,clock=lambda:self.now)
  self.l.seed_legacy('PFE',130,'original-incident')
 def test_time_restart_same_condition_cannot_replenish_budget(self):
  self.now+=10000;self.l=SubscriptionLifecycle(self.p,clock=lambda:self.now)
  self.assertFalse(self.l.reserve('PFE',('quotes',),'new-process')['allowed'])
  self.assertFalse(self.l.rearm('PFE','old-session',999))
  self.assertEqual(self.l.snapshot('PFE')['attempts'],4)
 def test_changed_condition_after_cooldown_rearms_once_and_keeps_new_limit(self):
  self.assertFalse(self.l.rearm('PFE','new-session',1001))
  self.now=1400;self.assertTrue(self.l.rearm('PFE','new-session',1400))
  for i in range(4):
   g=self.l.reserve('PFE',('quotes',),str(i),reason='RECOVERY');self.assertTrue(g['allowed']);self.l.finish(g,sent=True);self.now+=300
  self.assertFalse(self.l.rearm('PFE','new-session',self.now))
  self.assertFalse(self.l.reserve('PFE',('quotes',),'another')['allowed'])
 def test_unknown_request_cannot_be_rearmed(self):
  self.now=1400;self.l.rearm('PFE','new-session',1400)
  g=self.l.reserve('PFE',('quotes',),'one');self.l.finish(g,sent=False);self.now+=10000
  self.assertFalse(self.l.rearm('PFE','another-session',self.now))
  self.assertEqual(self.l.reserve('PFE',('quotes',),'two')['reason'],'PENDING_OR_UNKNOWN_REQUEST')
 def test_session_transition_only_rearms_after_cooldown_not_every_poll(self):
  r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
  r.observe('PFE',{},session='CLOSED');self.now=1400
  r.observe('PFE',{},session='REGULAR')
  self.assertIsNotNone(r.retry_due('PFE',session='REGULAR',connected=True))
  self.assertEqual(r.lifecycle.snapshot('PFE')['attempts'],0)
  g=r.lifecycle.reserve('PFE',('quotes',),'c',reason='RECOVERY');r.lifecycle.finish(g,sent=True)
  r.observe('PFE',{},session='REGULAR');r.retry_due('PFE',session='REGULAR',connected=True)
  self.assertEqual(r.lifecycle.snapshot('PFE')['attempts'],1)

 def test_explicit_calendar_session_is_verified_without_guessing_other_dates(self):
  from datetime import date
  from trading.market_session import _calendar_status_from_local_file,MarketSessionConfig
  today=_calendar_status_from_local_file(date(2026,10,29),MarketSessionConfig(require_verified_calendar=True))
  self.assertEqual(today.calendar_source_confidence,'high')
  unknown=_calendar_status_from_local_file(date(2026,11,3),MarketSessionConfig(require_verified_calendar=True))
  self.assertIsNone(unknown)

 def test_regular_open_is_new_condition_after_premarket_budget_exhausted(self):
  r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
  r.observe('PFE',{},session='PREMARKET');self.now=1400
  r.observe('PFE',{},session='REGULAR')
  self.assertIsNotNone(r.retry_due('PFE',session='REGULAR',connected=True))
  self.assertEqual(r.lifecycle.snapshot('PFE')['rearm_condition'],'session:REGULAR:0')

 def test_1102_alone_preserves_streams_but_later_session_can_rearm(self):
  r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
  r.observe('PFE',{},session='CLOSED')
  r.error('PFE',1100,'real link loss');self.now=1100
  r.error('PFE',1102,'data maintained');self.now=1400
  self.assertIsNone(r.retry_due('PFE',session='CLOSED',connected=True))
  self.assertEqual(r.lifecycle.snapshot('PFE')['attempts'],4)
  r.observe('PFE',{},session='PREMARKET')
  action=r.retry_due('PFE',session='PREMARKET',connected=True)
  self.assertEqual(action['action'],'RESUBSCRIBE_DATA')
  self.assertEqual(r.lifecycle.snapshot('PFE')['rearm_condition'],'session:PREMARKET:0')
  for i in range(4):
   grant=r.lifecycle.reserve('PFE',('quotes',),str(i),reason='RECOVERY')
   self.assertTrue(grant['allowed']);r.lifecycle.finish(grant,sent=True);self.now+=300
   if i<3:self.assertIsNotNone(r.retry_due('PFE',session='PREMARKET',connected=True))
  self.assertIsNone(r.retry_due('PFE',session='PREMARKET',connected=True))
  self.assertEqual(r.lifecycle.snapshot('PFE')['attempts'],4)

 def test_session_boundary_never_rearms_permission_review(self):
  r=SymbolRecovery(self.p,['PFE'],clock=lambda:self.now)
  r.observe('PFE',{},session='CLOSED');r.error('PFE',354,'not subscribed')
  self.now=1400;r.observe('PFE',{},session='REGULAR')
  self.assertIsNone(r.retry_due('PFE',session='REGULAR',connected=True))
  self.assertEqual(r.lifecycle.snapshot('PFE')['attempts'],4)
