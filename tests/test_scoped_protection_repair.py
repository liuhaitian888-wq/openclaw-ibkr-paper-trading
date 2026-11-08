from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import asyncio,hashlib,json,sqlite3,tempfile,unittest
from trading.protection_repair import ACCOUNT,SYMBOLS,validate_scope,plan,Journal,repair_once
from trading.audit import AuditLog
from reporting.recovery import RecoveryCoordinator
from reporting.agent_secretary import SecretaryArchive

NOW=datetime(2026,11,9,16,tzinfo=timezone.utc).timestamp()
class FakeBroker:
 def __init__(self,outcome=None):self.calls=[];self.outcome=outcome or {'status':'CONFIRMED'};self.old_age=0;self.quote_age=0
 def clock(self):return NOW
 async def snapshot(self):return {'account':ACCOUNT,'complete':True,'ends':['positions','orders','completed_orders','executions'],'positions':[position()],'orders':[],'observed_at':NOW,'oldest_end_at':NOW-self.old_age}
 async def details(self,p):return {'trading_hours':'20261109:0930-20261109:1600','timezone':'America/New_York','min_tick':.01}
 async def quote(self,p):return {'bid':100,'ask':100.01,'bid_at':NOW-self.quote_age,'ask_at':NOW,'data_type':1}
 async def submit_stop(self,p):
  self.calls.append(p)
  if isinstance(self.outcome,BaseException):raise self.outcome
  return self.outcome

def position():return dict(account=ACCOUNT,symbol='AAPL',quantity=17,con_id=123,currency='USD',sec_type='STK')

def authorize(root):
 SecretaryArchive(root/'agent_secretary.sqlite3').append('owner-protection','der-secretary',origin='USER',kind='PROTECTIVE_REPAIR_AUTHORIZATION',payload={'source':'CODEX_OWNER_CHAT','scope_id':'legacy-protection-20261109-v1','account':ACCOUNT,'max_quantities':SYMBOLS,'action':'ADD_MISSING_SELL_STOP_ONLY'})

class ScopedProtectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
  AuditLog(self.root/'trading_audit.sqlite3');RecoveryCoordinator(self.root/'runtime/recovery.sqlite3')
  for n in ['production.json','PAUSED','runtime/MAINTENANCE']:(self.root/n).write_text('preserved')
  self.actual={'commit':'sha','branch':'paper','code_root':'/approved','state_root':str(self.root)}
  self.scope={**self.actual,'id':'legacy-protection-20261109-v1','approved':True,'environment':'PAPER','account':ACCOUNT,'action':'ADD_MISSING_SELL_STOP_ONLY','allow_during_maintenance':True,'grants_entry_permission':False,'max_quantities':SYMBOLS,'max_submissions':5,'stop_fraction':'0.05','client_id':18992,'source_instruction':'codex-owner:01a1bd5c:delegated-limits:20261109','expires_at':'2026-11-09T21:00:00+00:00','preserved_files':{n:hashlib.sha256((self.root/n).read_bytes()).hexdigest() for n in ['production.json','PAUSED','runtime/MAINTENANCE']}}
  self.scope['approval_event']='owner-protection';authorize(self.root)
 def test_scope_identity_expiry_and_global_gate_drift_are_blocking(self):
  validate_scope(self.scope,self.actual,self.root,now=NOW)
  for changes in [{'account':'OTHER'},{'approved':False},{'stop_fraction':'.01'},{'max_submissions':6},{'expires_at':'2026-11-09T15:00:00+00:00'},{'grants_entry_permission':True}]:
   with self.subTest(changes=changes),self.assertRaises((PermissionError,ValueError)):validate_scope({**self.scope,**changes},self.actual,self.root,now=NOW)
  (self.root/'PAUSED').write_text('changed')
  with self.assertRaises(PermissionError):validate_scope(self.scope,self.actual,self.root,now=NOW)
 def test_exact_reducing_stop_and_existing_order_preservation(self):
  q=dict(bid=100,ask=100.01,bid_at=NOW,ask_at=NOW,data_type=1)
  p=plan(self.scope,position(),[],q,now=NOW,min_tick=.01)
  self.assertEqual(p['quantity'],17);self.assertEqual(p['stop_price'],'95.00');self.assertEqual(p['side'],'SELL')
  for changes in [{'symbol':'PFE'},{'quantity':18},{'quantity':-1},{'quantity':1.5},{'currency':'EUR'}]:
   with self.subTest(changes=changes),self.assertRaises(PermissionError):plan(self.scope,{**position(),**changes},[],q,now=NOW,min_tick=.01)
  for changes in [{'bid_at':NOW-4},{'data_type':3},{'bid':float('nan')},{'ask':99},{'bid_at':NOW+1}]:
   with self.subTest(changes=changes),self.assertRaises(PermissionError):plan(self.scope,position(),[],{**q,**changes},now=NOW,min_tick=.01)
  with self.assertRaises(PermissionError):plan(self.scope,position(),[dict(account=ACCOUNT,symbol='AAPL',side='SELL',status='PreSubmitted')],q,now=NOW,min_tick=.01)
 def test_closed_session_and_stale_readback_never_reserve_or_submit(self):
  b=FakeBroker();result=asyncio.run(repair_once(self.scope,self.actual,self.root,b,now=NOW-3600*7))
  self.assertEqual(result['state'],'WAIT_SESSION');self.assertEqual(b.calls,[])
  b.old_age=6
  with self.assertRaises(PermissionError):asyncio.run(repair_once(self.scope,self.actual,self.root,b,now=NOW))
  self.assertEqual(b.calls,[])
 def test_stale_quote_waits_without_spending_order_budget(self):
  b=FakeBroker();b.quote_age=4
  r=asyncio.run(repair_once(self.scope,self.actual,self.root,b,now=NOW))
  self.assertEqual(r['state'],'WAIT_EVIDENCE');self.assertEqual(Journal(self.root/'trading_audit.sqlite3',self.scope['id']).attempts(),{})
 def test_success_exactly_once_with_audit_and_global_pauses_preserved(self):
  b=FakeBroker();r=asyncio.run(repair_once(self.scope,self.actual,self.root,b,now=NOW))
  self.assertEqual(r['state'],'CONFIRMED');self.assertEqual(len(b.calls),1)
  asyncio.run(repair_once(self.scope,self.actual,self.root,b,now=NOW));self.assertEqual(len(b.calls),1)
  validate_scope(self.scope,self.actual,self.root,now=NOW)
 def test_unknown_exception_and_interruption_survive_restart_without_replay(self):
  for outcome in [{'status':'UNKNOWN'},RuntimeError('ack lost'),KeyboardInterrupt()]:
   with self.subTest(outcome=type(outcome).__name__):
    # Each subcase uses its own exact occurrence/database, not a reset budget.
    with tempfile.TemporaryDirectory() as tmp:
     r=Path(tmp);(r/'runtime').mkdir();AuditLog(r/'trading_audit.sqlite3');RecoveryCoordinator(r/'runtime/recovery.sqlite3')
     authorize(r)
     for name in self.scope['preserved_files']:(r/name).write_text('preserved')
     actual={**self.actual,'state_root':str(r)};scope={**self.scope,**actual}
     b=FakeBroker(outcome)
     if isinstance(outcome,BaseException) and not isinstance(outcome,Exception):
      with self.assertRaises(KeyboardInterrupt):asyncio.run(repair_once(scope,actual,r,b,now=NOW))
     else:self.assertEqual(asyncio.run(repair_once(scope,actual,r,b,now=NOW))['state'],'RECONCILIATION_REQUIRED')
     self.assertEqual(asyncio.run(repair_once(scope,actual,r,b,now=NOW))['state'],'RECONCILIATION_REQUIRED');self.assertEqual(len(b.calls),1)
