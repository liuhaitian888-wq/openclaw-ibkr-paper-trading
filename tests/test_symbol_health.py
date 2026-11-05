import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from trading.symbol_health import classify_symbol, SymbolRecovery, session_for_symbol

class SymbolHealthTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.now=1000;self.path=Path(self.tmp.name)/'recovery.db'
  self.r=SymbolRecovery(self.path,['GOOD','BAD'],clock=lambda:self.now)
 def fields(self,kind=1):return dict(data_type=kind,bid=10,ask=11,bid_at=self.now,ask_at=self.now)
 def test_types_and_partial_updates(self):
  for t,expected in ((1,'REALTIME_HEALTHY'),(2,'FROZEN'),(3,'DELAYED'),(4,'DELAYED_FROZEN'),(None,'UNKNOWN')):
   h=classify_symbol(self.fields(t),self.now,session='REGULAR');self.assertEqual(h['status'],expected)
  f=self.fields();f['bid_at']-=6
  self.assertEqual(classify_symbol(f,self.now)['status'],'REALTIME_STALE')
  f['permission_denied']=True;self.assertEqual(classify_symbol(f,self.now)['status'],'PERMISSION_DENIED')
 def test_clock_nan_halt_and_no_trade_distinction(self):
  for value in (float('nan'),float('inf'),-1):
   f=self.fields();f['bid']=value;self.assertFalse(classify_symbol(f,self.now,session='REGULAR')['allows_realtime'])
  f=self.fields();f['ask_at']+=1;self.assertFalse(classify_symbol(f,self.now,session='REGULAR')['allows_realtime'])
  self.assertFalse(classify_symbol(self.fields(),self.now,session='REGULAR',halted=2)['allows_realtime'])
  self.assertTrue(classify_symbol(self.fields(),self.now,session='REGULAR')['allows_realtime']) # no Last required
  self.assertFalse(classify_symbol(self.fields(),self.now,session='HOLIDAY')['allows_realtime'])
 def test_durable_budget_and_symbol_isolation(self):
  self.r.error('BAD',10197,'competing')
  self.assertIsNone(self.r.retry_due('GOOD',session='REGULAR',connected=True))
  for step in range(4):
   self.now+=300;self.r=SymbolRecovery(self.path,['GOOD','BAD'],clock=lambda:self.now)
   self.r.error('BAD',10197,'same ongoing conflict')
   self.assertEqual(self.r.retry_due('BAD',session='REGULAR',connected=True)['attempt'],step+1)
   self.assertIsNone(self.r.retry_due('BAD',session='REGULAR',connected=True))
  self.now+=10000;self.r.error('BAD',10197,'still same');self.assertIsNone(self.r.retry_due('BAD',session='REGULAR',connected=True))
 def test_shared_budget_requires_explicit_scope(self):
  self.r.error('BAD',10197,'all affected',confirmed_shared=True);self.now+=30
  action=self.r.retry_due('GOOD',session='REGULAR',connected=True)
  self.assertEqual(set(action['symbols']),{'GOOD','BAD'})
  self.assertIsNone(self.r.retry_due('BAD',session='REGULAR',connected=True))
 def test_error_actions_closed_and_retained_subscription(self):
  for code,action in ((1100,'WAIT_CONNECTION'),(1102,'RECONCILE_ONLY'),(101,'HUMAN_REVIEW'),(321,'DIAGNOSE_MESSAGE'),(162,'DIAGNOSE_MESSAGE')):
   self.assertEqual(self.r.error('BAD',code,'details')['action'],action)
   self.assertIsNone(self.r.retry_due('BAD',session='REGULAR',connected=True))
  self.r.error('GOOD',10225,'bust')
  self.assertIsNone(self.r.retry_due('GOOD',session='CLOSED',connected=True))
  self.assertEqual(self.r.retry_due('GOOD',session='REGULAR',connected=True)['action'],'RESUBSCRIBE_BARS')
 def test_notification_and_evidence_backed_recovery(self):
  self.r.observe('BAD',{},session='REGULAR');self.now+=61
  self.r.observe('BAD',{},session='REGULAR');self.r.observe('BAD',{},session='REGULAR')
  first=self.r.store.claim();self.assertEqual(first['kind'],'ALERT');self.r.store.finish(first['id'],'SMTP_ACCEPTED')
  for _ in range(3):
   self.now+=1;self.r.observe('BAD',self.fields(),session='REGULAR')
  recovery=self.r.store.claim();self.assertEqual(recovery['kind'],'RECOVERY');self.r.store.finish(recovery['id'],'SMTP_ACCEPTED')
  self.assertTrue(self.r.verified_recovery('BAD'));self.assertFalse(self.r.verified_recovery('GOOD'))
  self.r.observe('BAD',self.fields(),session='REGULAR');self.assertIsNone(self.r.store.claim())
 def test_no_closed_notifications_and_identical_quote_not_validation(self):
  self.r.observe('BAD',{},session='CLOSED');self.now+=100;self.r.observe('BAD',{},session='CLOSED');self.assertIsNone(self.r.store.claim())
  f=self.fields()
  for _ in range(3):self.r.observe('BAD',f,session='REGULAR')
  self.assertFalse(self.r.verified_recovery('BAD'))
 def test_calendar_holiday_early_close_and_dst(self):
  from datetime import datetime
  for date,expected in (('2026-07-04T16:00:00+00:00','WEEKEND'),):
   self.assertEqual(session_for_symbol(datetime.fromisoformat(date).timestamp()),expected)
  # Unknown calendar never substitutes a weekday assumption.
  with patch('trading.market_session._calendar_status_from_package',return_value=None),patch('trading.market_session._calendar_status_from_local_file',return_value=None):
   self.assertEqual(session_for_symbol(datetime.fromisoformat('2026-10-28T16:00:00+00:00').timestamp()),'SESSION_UNKNOWN')

 def test_verified_calendar_holiday_early_close_dst(self):
  from datetime import datetime,time
  from trading.market_session import CalendarStatus
  for instant,cal,expected in (
   ('2026-12-25T16:00:00+00:00',CalendarStatus(False,True,False,time(16),'official_fixture','high'),'HOLIDAY'),
   ('2026-11-27T17:00:00+00:00',CalendarStatus(True,False,True,time(13),'official_fixture','high'),'EARLY_CLOSE'),
   ('2026-03-09T13:30:00+00:00',CalendarStatus(True,False,False,time(16),'official_fixture','high'),'REGULAR'),
   ('2026-11-02T14:30:00+00:00',CalendarStatus(True,False,False,time(16),'official_fixture','high'),'REGULAR')):
   with patch('trading.market_session.calendar_status',return_value=cal):
    self.assertEqual(session_for_symbol(datetime.fromisoformat(instant).timestamp()),expected)

 def test_additive_gate_never_accepts_missing_stale_or_incomplete_recovery(self):
  from trading.symbol_health import symbol_market_permission
  self.assertFalse(symbol_market_permission({},self.now)['allowed'])
  state=self.r.observe('GOOD',self.fields(),session='REGULAR')
  self.assertTrue(symbol_market_permission(state,self.now)['allowed'])
  self.assertFalse(symbol_market_permission(state,self.now+6)['allowed'])
  state['fault_active']=True;self.assertFalse(symbol_market_permission(state,self.now)['allowed'])

 def test_hmds_explicit_session_conflict_remains_recoverable(self):
  s=self.r.error('BAD',162,'Historical Market Data Service error message:Trading TWS session is connected from a different IP address')
  self.assertEqual(s['code'],10197)
  self.assertEqual(s['action'],'RESUBSCRIBE_DATA')
  self.now+=30
  self.assertIsNotNone(self.r.retry_due('BAD',session='PREMARKET',connected=True))

 def test_secondary_history_error_does_not_disable_quote_collision_recovery(self):
  self.r.error('BAD',10197,'competing')
  s=self.r.error('BAD',162,'Historical Market Data Service error: query unavailable')
  self.assertEqual(s['code'],10197)
  self.assertEqual(s['secondary_error']['code'],162)
  self.now+=30
  self.assertIsNotNone(self.r.retry_due('BAD',session='PREMARKET',connected=True))

 def test_legacy_hmds_session_error_adopted_without_budget_reset(self):
  from contextlib import closing
  import json
  self.r.lifecycle.seed_legacy('BAD',4,'old')
  old=dict(code=162,details='Trading TWS session is connected from a different IP address',
           action='DIAGNOSE_MESSAGE',phase='BLOCKED',attempts=4,next_retry=None,episode=7)
  with closing(self.r.store.connect()) as c,c:
   c.execute('INSERT OR REPLACE INTO symbol_health_runtime VALUES (?,?)',('@retry:BAD',json.dumps(old)))
  r=SymbolRecovery(self.path,['GOOD','BAD'],clock=lambda:self.now)
  self.assertEqual(r.lifecycle.snapshot('BAD')['attempts'],4)
  with closing(r.store.connect()) as c:s=r._read(c,'@retry:BAD')
  self.assertEqual(s['code'],10197);self.assertEqual(s['original_code'],162)
  self.assertEqual(s['attempts'],4);self.assertEqual(s['episode'],7)
  stamp=s['classification_corrected_at'];self.now+=1
  r=SymbolRecovery(self.path,['GOOD','BAD'],clock=lambda:self.now)
  with closing(r.store.connect()) as c:s=r._read(c,'@retry:BAD')
  self.assertEqual(s['classification_corrected_at'],stamp)
