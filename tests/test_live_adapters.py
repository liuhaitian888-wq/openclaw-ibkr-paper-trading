import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from reporting.recovery import RecoveryCoordinator,wire_live_adapters,RECOVERY_STEPS,audit_write_probe
from trading.order_ownership import verified_historical_intents,classify_order

class LiveAdapterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.co=RecoveryCoordinator(self.root/'runtime/recovery.sqlite3')
 def bundle(self):
  from datetime import datetime,timezone
  return dict(complete=True,account_id='DU1',environment='PAPER',server_time=time.time(),observed_at=datetime.now(timezone.utc).isoformat(),
    account={'net':{'value':1,'currency':'EUR'}},pnl={'daily':0},positions=[],orders=[],executions=[],quotes={'AAPL':{'data_type':1,'bid':1,'ask':2,'received_at':'now'}})
 def adapters(self,b):return wire_live_adapters(self.co,self.root,self.root,expected_account='DU1',symbols=('AAPL',),broker_probe=lambda **kw:b)
 def test_live_evidence_all_phases_and_account_scope(self):
  b=self.bundle();a=self.adapters(b)['ACCOUNT']
  self.assertTrue(all(a(step) for step in RECOVERY_STEPS))
  self.assertEqual(a.observation['evidence']['account_id'],'DU1')
  b['account_id']='OTHER';self.assertFalse(self.adapters(b)['ACCOUNT']('connect'))
 def test_missing_quotes_and_incomplete_callbacks_never_pass(self):
  b=self.bundle();b['quotes']={};self.assertFalse(self.adapters(b)['MARKET_DATA']('connect'))
  b=self.bundle();b['complete']=False;self.assertFalse(self.adapters(b)['ORDERS']('connect'))
 def test_unknown_backlog_is_not_promoted_or_replayed(self):
  self.co.begin_operation('order:one','order',{})
  a=self.adapters(self.bundle())['ORDERS'];self.assertTrue(a('connect'));self.assertFalse(a('backlog'))
  restarted=RecoveryCoordinator(self.co.path);self.assertFalse(restarted.begin_operation('order:one','order',{}))
 def test_adapter_cannot_create_missing_database(self):
  with self.assertRaises(sqlite3.Error):audit_write_probe(self.root/'absent.sqlite3')
  self.assertFalse((self.root/'absent.sqlite3').exists())
 def test_db_failure_invalidates_descendants_until_readback(self):
  from reporting.health import MODULE_DEPENDENCIES
  for name in MODULE_DEPENDENCIES:self.co.observe(name,'HEALTHY',freshness='FRESH')
  self.co.observe('DATABASE','FAILED',reason='disk full')
  self.co.observe('DATABASE','HEALTHY',freshness='FRESH')
  self.assertNotEqual(self.co.snapshot()['ORDER_SUBMISSION']['state'],'HEALTHY')
  self.assertNotEqual(self.co.snapshot()['DELIVERY']['state'],'HEALTHY')
  self.assertEqual(self.co.snapshot()['DIAGNOSTICS']['state'],'HEALTHY')
 def test_actual_gate_refuses_audit_failure_even_if_cached_green(self):
  import trading.production_guard as g
  with patch.object(g,'module_gate',return_value={'allowed':True}),patch('trading.production_paths.AUDIT_DB',self.root/'missing.sqlite3'),patch.object(g,'RUNTIME_ROOT',self.root/'runtime'):
   for action in ('ORDER_SUBMISSION_ALLOWED','FEISHU_SEND_ALLOWED'):
    with self.assertRaises(PermissionError):g.require_module_gate(action)
  self.assertEqual(self.co.observations()['DATABASE']['state'],'FAILED')
 def test_actual_gate_refuses_locked_state_database(self):
  import trading.production_guard as g
  with closing(self.co.connect()) as locked:
   locked.execute('BEGIN EXCLUSIVE')
   with patch.object(g,'module_gate',return_value={'allowed':True}),patch('reporting.recovery.audit_write_probe'),patch.object(g,'RUNTIME_ROOT',self.root/'runtime'):
    with self.assertRaises(PermissionError):g.require_module_gate('FEISHU_SEND_ALLOWED')
   locked.rollback()
 def test_historical_provenance_hash_scope_and_no_mutation(self):
  source=self.root/'source.json';source.write_text('{"original":true}')
  order={'account':'DU1','perm_id':5,'order_ref':'protect-1'}
  binding={'account':'DU1','environment':'PAPER','perm_id':5,'intent_id':'protect-1','strategy':'position_protection','source_path':str(source),'source_id':hashlib.sha256(source.read_bytes()).hexdigest()}
  review=self.root/'review.json';review.write_text(json.dumps({'ownership':'SYSTEM_OWNED','binding':binding,'mutation_authorized':False}))
  intents=verified_historical_intents(order,[review],account='DU1',environment='PAPER')
  outcome=classify_order(order,intents,account='DU1',environment='PAPER')
  self.assertEqual(outcome['ownership'],'SYSTEM_OWNED');self.assertFalse(outcome['may_modify'])
  self.assertEqual(verified_historical_intents(order,[review],account='OTHER',environment='PAPER'),[])
  source.write_text('changed');self.assertEqual(verified_historical_intents(order,[review],account='DU1',environment='PAPER'),[])
 def test_force_refresh_never_accepts_cached_feishu_token(self):
  from scripts.send_feishu_report import tenant_access_token
  with patch.dict('os.environ',{'FEISHU_TENANT_ACCESS_TOKEN':'cached','FEISHU_APP_ID':'','FEISHU_APP_SECRET':''}):
   with self.assertRaises(RuntimeError):tenant_access_token(force_refresh=True)

 def test_stream_stop_joins_reader_captured_before_disconnect(self):
  from trading.ibkr_streaming import IbkrStreamingQuoteSource
  from tests.test_ibkr_streaming import FakeStreamingClient
  class Reader:
   joined=False
   def join(self,timeout):self.joined=True
   def is_alive(self):return not self.joined
  reader=Reader()
  class Client(FakeStreamingClient):
   def disconnect(self):super().disconnect();self.reader=None
  source=IbkrStreamingQuoteSource(symbols=['AAPL'],client_factory=Client)
  self.assertTrue(source.start(.01));source._client.reader=reader;source.stop()
  self.assertTrue(reader.joined)

 def test_transport_timeout_has_durable_attempt_and_no_replay(self):
  import trading.production_guard as g
  calls=[]
  @g.guarded_broker_operation
  def transport(order_ref):
   calls.append(order_ref)
   self.assertEqual(self.co.uncertainties()[0][2],'STARTED')
   raise TimeoutError('ambiguous transport')
  with patch('trading.production_paths.CODE_ROOT',self.root),patch('trading.production_paths.PRODUCTION_WORKSPACE',self.root),patch.object(g,'RUNTIME_ROOT',self.root/'runtime'),patch.object(g,'require_module_gate'):
   with self.assertRaises(TimeoutError):transport('identity-1')
   with self.assertRaises(PermissionError):transport('identity-1')
  self.assertEqual(calls,['identity-1']);self.assertEqual(self.co.uncertainties()[0][2],'UNKNOWN')
 def test_delivery_started_and_unknown_never_invoke_transport(self):
  from scripts.report_delivery_guard import deliver
  from datetime import datetime
  from zoneinfo import ZoneInfo
  from unittest.mock import Mock
  now=datetime(2026,9,9,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))
  report=self.root/'report.json';report.write_text('{"trading_date":"2026-09-08"}')
  for status in ('STARTED','UNKNOWN','SENT_ACCEPTED'):
   (self.root/'delivery.json').write_text(json.dumps({'reports':{'daily:2026-09-08:scheduled-close':{'status':status}}}))
   transport=Mock()
   self.assertEqual(deliver(report,transport,state_dir=self.root,now=now)['status'],'DUPLICATE')
   transport.assert_not_called()

 def test_existing_audit_keys_never_overwrite_other_scopes(self):
  from trading.audit import AuditLog
  audit=AuditLog(self.root/'audit.sqlite3')
  old={'order_id':1,'perm_id':8,'account':'DU1','environment':'PAPER','source':'ibkr','run':'r1','occurrence':'o1','status':'Submitted'}
  execution={**old,'exec_id':'e1'}
  audit.reconcile([old],[execution],[])
  for field,value in (('account','DU2'),('environment','LIVE'),('source','other'),('run','r2'),('occurrence','o2'),('perm_id',9)):
   for orders,executions in (([{**old,field:value}],[]),([],[{**execution,field:value}])):
    with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):audit.reconcile(orders,executions,[])
  with closing(sqlite3.connect(self.root/'audit.sqlite3')) as c:
   self.assertEqual(json.loads(c.execute('SELECT raw_json FROM broker_orders').fetchone()[0])['account'],'DU1')
  audit.reconcile([{**old,'status':'Filled'}],[],[])

 def test_actual_connected_account_must_match_approved_identity(self):
  import trading.production_guard as g
  (self.root/'production.json').write_text(json.dumps({'ready':True,'account':'DU1','environment':'PAPER'}))
  with patch('trading.production_paths.CODE_ROOT',self.root),patch('trading.production_paths.PRODUCTION_WORKSPACE',self.root),patch.object(g,'STATE_ROOT',self.root):
   g.require_connected_account(['DU1'])
   with self.assertRaises(PermissionError):g.require_connected_account(['DU2'])
