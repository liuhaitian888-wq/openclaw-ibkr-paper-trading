from contextlib import closing
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import asyncio,hashlib,json,sqlite3,tempfile,time,unittest
from trading.cash_conversion import ACCOUNT,SCOPE,validate,plan,reconcile
from trading.audit import AuditLog
from reporting.recovery import RecoveryCoordinator
from ops.cloud.cash_conversion import run

class CashConversionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
  self.actual={'commit':'sha','branch':'paper','code_root':'/approved','state_root':str(self.root)}
  for n in ['production.json','PAUSED','runtime/MAINTENANCE']:(self.root/n).write_text('preserve')
  (self.root/'runtime/funding-policy.json').write_text(json.dumps(dict(approved=True,account=ACCOUNT,environment='PAPER',mode='CASH_ONLY_NO_NEW_BORROWING',automatic_fx_approved=True,allow_new_currency_debit=False)))
  self.scope={**self.actual,'id':SCOPE,'approved':True,'account':ACCOUNT,'environment':'PAPER','action':'CASH_FUNDED_EUR_TO_USD_ONLY','max_eur_spend':65000,'target_usd_cash':2010,'fee_reserve_eur':5,'max_submissions':1,'grants_stock_entry_permission':False,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'preserved_files':{n:hashlib.sha256((self.root/n).read_bytes()).hexdigest() for n in ['production.json','PAUSED','runtime/MAINTENANCE']}}
  (self.root/'runtime/cash-conversion-scope.json').write_text(json.dumps(self.scope));AuditLog(self.root/'trading_audit.sqlite3');RecoveryCoordinator(self.root/'runtime/recovery.sqlite3')
 def book(self):return dict(source='BROKER_API',account=ACCOUNT,base_currency='EUR',observed_at=datetime.now(timezone.utc).isoformat(),requested_currencies=['USD','EUR'],currencies={'USD':{'amount':'-69788.66'},'EUR':{'amount':'1007456.40'}})
 def quote(self):return dict(bid=1.1145,ask=1.11453,bid_at=time.time(),ask_at=time.time(),data_type=1)
 def test_plan_cash_direction_ceiling_fees_and_units(self):
  p=plan(self.scope,self.book(),self.quote(),min_tick=.00005,commission_eur=1.8,now=time.time())
  self.assertEqual(p['side'],'SELL');self.assertEqual(p['currency'],'USD');self.assertLess(p['quantity']+5,65000)
  for quote_changes in [{'data_type':3},{'bid_at':0},{'bid':float('nan')}]:
   with self.subTest(changes=quote_changes),self.assertRaises((PermissionError,ArithmeticError)):plan(self.scope,self.book(),{**self.quote(),**quote_changes},min_tick=.00005,commission_eur=1.8,now=time.time())
  for fee in [float('nan'),6,-1]:
   with self.subTest(fee=fee),self.assertRaises((PermissionError,ArithmeticError)):plan(self.scope,self.book(),self.quote(),min_tick=.00005,commission_eur=fee,now=time.time())
  book=self.book();book['currencies']['EUR']['amount']='100'
  with self.assertRaises(PermissionError):plan(self.scope,book,self.quote(),min_tick=.00005,commission_eur=1.8,now=time.time())
 def test_real_runner_reserves_before_single_submit_and_proves_cash_deltas(self):
  test=self;calls=[]
  class B:
   def clock(self):return time.time()
   async def connect(self):pass
   def close(self):calls.append('close')
   async def snapshot(self):return dict(account=ACCOUNT,complete=True,ends=['positions','orders','completed_orders','executions'],oldest_end_at=time.time(),positions=[dict(account=ACCOUNT,con_id=1,quantity='17',sec_type='STK')],orders=[])
   async def reference(self):return NS(minTick=.00005,liquidHours='20260101:0000-20270101:0000',timeZoneId='UTC')
   async def cashbook(self):return test.book()
   def quote(self):return test.quote()
   async def estimate(self,p):return 1.8
   async def submit(self,p):
    calls.append('submit')
    with closing(sqlite3.connect(test.root/'trading_audit.sqlite3')) as c:test.assertEqual(c.execute('SELECT status FROM cash_conversion_attempts').fetchone()[0],'STARTED')
    after=test.book();after['currencies']['EUR']['amount']=str(Decimal(p['before_eur'])-p['quantity']-Decimal('1.8'));after['currencies']['USD']['amount']=str(Decimal(p['before_usd'])+Decimal(p['expected_min_usd_credit']))
    return dict(status='FILLED',filled_eur=str(p['quantity']),commission_eur='1.8',execution_ids=['fx-exec-1'],snapshot=await self.snapshot(),cashbook=after)
  with patch('ops.cloud.cash_conversion.Broker',B),patch('ops.cloud.cash_conversion.context',return_value=self.actual):
   r=asyncio.run(run(self.root));self.assertEqual(r['state'],'FILLED')
   with self.assertRaises(PermissionError):asyncio.run(run(self.root))
  self.assertEqual(calls.count('submit'),1);self.assertEqual(calls.count('close'),2)
  self.assertEqual(AuditLog(self.root/'trading_audit.sqlite3').paper_notional_for_date(datetime.now(timezone.utc).date().isoformat(),'UTC'),0)
  self.assertTrue((self.root/'PAUSED').exists())
  bad={**r['native']['cashbook'],'account':'OTHER'}
  self.assertFalse(reconcile(r['plan'],bad,filled_eur=r['plan']['quantity'],commission_eur=1.8,open_scope_orders=[],execution_ids=['x']))
 def test_scope_mismatch_or_expiry_never_grants_a_conversion(self):
  for changes in [{'approved':False},{'max_eur_spend':1000000},{'grants_stock_entry_permission':True},{'expires_at':'2026-01-01T00:00:00+00:00'}]:
   with self.subTest(changes=changes),self.assertRaises(PermissionError):validate({**self.scope,**changes},self.actual,self.root,now=time.time())
 def test_transport_failure_keeps_original_plan_and_global_unknown_without_replay(self):
  test=self;calls=[]
  class B:
   def clock(self):return time.time()
   async def connect(self):pass
   def close(self):calls.append('close')
   async def snapshot(self):return dict(account=ACCOUNT,complete=True,ends=['positions','orders','completed_orders','executions'],oldest_end_at=time.time(),positions=[],orders=[])
   async def reference(self):return NS(minTick=.00005,liquidHours='20260101:0000-20270101:0000',timeZoneId='UTC')
   async def cashbook(self):return test.book()
   def quote(self):return test.quote()
   async def estimate(self,p):return 1.8
   async def submit(self,p):calls.append('submit');raise ConnectionError('acknowledgement lost')
  with patch('ops.cloud.cash_conversion.Broker',B),patch('ops.cloud.cash_conversion.context',return_value=self.actual):
   with self.assertRaises(ConnectionError):asyncio.run(run(self.root))
   with self.assertRaises(PermissionError):asyncio.run(run(self.root))
  self.assertEqual(calls,['submit','close'])
  with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c:
   status,payload=c.execute('SELECT status,payload FROM cash_conversion_attempts').fetchone()
   self.assertEqual(status,'UNKNOWN');self.assertEqual(json.loads(payload)['plan']['account'],ACCOUNT)
  self.assertEqual(RecoveryCoordinator(self.root/'runtime/recovery.sqlite3').uncertainties()[0][2],'UNKNOWN')

 def test_approved_continuous_cash_owner_keeps_finite_fx_from_overwriting_latest(self):
  from ops.cloud.cash_conversion import publish_legacy_cashbook
  target=self.root/'runtime/currency-book.latest.json';target.write_text('continuous-native-facts')
  (self.root/'runtime/monitoring-deployment.json').write_text(json.dumps({'native_cashbook_observation_approved':True}))
  self.assertEqual(publish_legacy_cashbook(self.root,self.book()),'CONTINUOUS_OWNER_CONFIGURED')
  self.assertEqual(target.read_text(),'continuous-native-facts')
 def test_unknown_cash_owner_and_file_failure_do_not_reclassify_known_fx_outcome(self):
  from ops.cloud.cash_conversion import publish_legacy_cashbook
  (self.root/'runtime/monitoring-deployment.json').write_text('{')
  self.assertEqual(publish_legacy_cashbook(self.root,self.book()),'SKIPPED_OWNER_UNVERIFIED')
  (self.root/'runtime/monitoring-deployment.json').unlink()
  (self.root/'runtime/currency-book.latest.fx.tmp').write_text('retained incomplete evidence')
  self.assertEqual(publish_legacy_cashbook(self.root,self.book()),'PUBLICATION_FAILED_NATIVE_RECEIPT_RETAINED')
  self.assertEqual((self.root/'runtime/currency-book.latest.fx.tmp').read_text(),'retained incomplete evidence')

 def test_legacy_cash_file_is_private_and_uses_only_its_own_temporary(self):
  from ops.cloud.cash_conversion import publish_legacy_cashbook
  self.assertEqual(publish_legacy_cashbook(self.root,self.book()),'LEGACY_BOOK_PUBLISHED')
  self.assertEqual((self.root/'runtime/currency-book.latest.json').stat().st_mode&0o077,0)
  self.assertFalse((self.root/'runtime/currency-book.latest.fx.tmp').exists())
