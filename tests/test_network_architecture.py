import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from reporting.health import MODULE_DEPENDENCIES,resolve_modules,safety_gate
from reporting.recovery import RecoveryCoordinator,RECOVERY_STEPS
from trading.order_ownership import classify_order,exposure_snapshot,occurrence_scope

class NetworkArchitectureTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'state.sqlite3';self.time=[1788889000.0]
  self.co=RecoveryCoordinator(self.path,clock=lambda:self.time[0])
 def healthy(self):
  for name in MODULE_DEPENDENCIES:self.co.observe(name,'HEALTHY',freshness='FRESH',reason='mock verified')
 def test_offline_isolation_and_individual_dependencies(self):
  self.healthy();self.co.observe('NETWORK','OFFLINE',reason='fault injection')
  s=self.co.snapshot()
  for name in ('DATABASE','AUDIT','LOCAL_STATE','REPORT_ARCHIVE','REPORT','DIAGNOSTICS'):self.assertEqual(s[name]['state'],'HEALTHY')
  for name in ('STRATEGY','DELIVERY','ACCOUNT','ORDERS'):self.assertEqual(s[name]['state'],'WAITING_DEPENDENCY')
  self.assertEqual(s['MARKET_DATA']['freshness'],'STALE')
  self.healthy();self.co.observe('FEISHU','OFFLINE');s=self.co.snapshot();self.assertEqual(s['STRATEGY']['state'],'HEALTHY');self.assertEqual(s['DELIVERY']['state'],'WAITING_DEPENDENCY')
  self.healthy();self.co.observe('IBKR_CONNECTION','OFFLINE');s=self.co.snapshot();self.assertEqual(s['DELIVERY']['state'],'HEALTHY');self.assertEqual(s['STRATEGY']['state'],'WAITING_DEPENDENCY')
 def test_start_offline_stale_short_long_and_socket_only(self):
  self.assertNotEqual(self.co.snapshot()['STRATEGY']['state'],'HEALTHY')
  self.healthy();self.time[0]+=121;s=self.co.snapshot();self.assertEqual(s['MARKET_DATA']['freshness'],'STALE')
  self.co.observe('NETWORK','HEALTHY',freshness='FRESH');self.co.observe('IBKR_CONNECTION','HEALTHY',freshness='FRESH')
  self.assertEqual(self.co.snapshot()['STRATEGY']['state'],'WAITING_DEPENDENCY')
 def test_recovery_order_flap_and_backoff(self):
  self.healthy();calls=[]
  def adapter(step):calls.append(step);return True
  self.co.adapters={'IBKR_CONNECTION':adapter};self.co.observe('IBKR_CONNECTION','OFFLINE')
  self.assertEqual(self.co.tick(),['IBKR_CONNECTION']);self.assertEqual(calls,list(RECOVERY_STEPS));self.assertEqual(self.co.tick(),[])
  self.co.observe('IBKR_CONNECTION','OFFLINE');self.assertEqual(self.co.tick(),[])
  self.time[0]+=11
  def flap(step):
   if step=='refresh':self.co.observe('NETWORK','OFFLINE')
   return True
  self.co.adapters['IBKR_CONNECTION']=flap;self.co.tick();self.assertNotEqual(self.co.snapshot()['IBKR_CONNECTION']['state'],'HEALTHY')
 def test_durable_unknown_restart_and_no_side_effect_replay(self):
  self.assertTrue(self.co.begin_operation('order-1','order',{}));self.assertTrue(self.co.begin_operation('delivery-1','delivery',{}))
  new=RecoveryCoordinator(self.path,clock=lambda:self.time[0]);self.assertEqual(len(new.uncertainties()),2)
  self.assertFalse(new.begin_operation('order-1','order',{}));new.finish_operation('delivery-1','UNKNOWN');self.assertFalse(new.begin_operation('delivery-1','delivery',{}))
  new.tick();self.assertEqual(len(new.uncertainties()),2)
 def test_sqlite_lock_blocks_before_operation(self):
  with closing(sqlite3.connect(self.path)) as c:
   c.execute('BEGIN IMMEDIATE')
   with self.assertRaises(sqlite3.OperationalError):self.co.begin_operation('never-sent','order',{})
   c.rollback()
  self.assertEqual(self.co.uncertainties(),[])
 def test_cross_coordinator_lease_and_interrupted_recovery(self):
  self.healthy();self.co.observe('IBKR_CONNECTION','OFFLINE');started=threading.Event();release=threading.Event()
  def adapter(step):
   if step=='connect':started.set();release.wait(2)
   return True
  self.co.adapters={'IBKR_CONNECTION':adapter};worker=threading.Thread(target=self.co.tick);worker.start();self.assertTrue(started.wait(1))
  other=RecoveryCoordinator(self.path,{'IBKR_CONNECTION':lambda step:True},clock=lambda:self.time[0]);self.assertEqual(other.tick(),[]);release.set();worker.join(3);self.assertFalse(worker.is_alive())
  with closing(sqlite3.connect(self.path)) as c,c:c.execute("UPDATE recovery_jobs SET state='RUNNING'")
  other.observe('IBKR_CONNECTION','OFFLINE');self.assertEqual(other.tick(),['IBKR_CONNECTION'])
 def test_320_recovery_cycles_no_threads_or_fd_growth(self):
  import socket
  def adapter(step):
   if step=='connect':
    left,right=socket.socketpair()
    with closing(left),closing(right):
     left.send(b'x');self.assertEqual(right.recv(1),b'x')
   return True
  self.healthy();self.co.adapters={'IBKR_CONNECTION':adapter};threads=threading.active_count();samples=[]
  for i in range(320):
   self.time[0]+=301;self.healthy();self.co.observe('IBKR_CONNECTION','OFFLINE');self.co.tick()
   if i%32==0:samples.append(len(os.listdir('/dev/fd')))
  self.assertEqual(threading.active_count(),threads);self.assertLessEqual(max(samples)-min(samples),1)
  self.assertEqual(self.co.uncertainties(),[])
  print('Recovery endurance:',{'cycles':320,'fd_min':min(samples),'fd_max':max(samples),'threads_before':threads,'threads_after':threading.active_count(),'sockets_closed':640})
 def test_manual_order_visible_not_mutable_and_scope_isolation(self):
  order={'account':'DUQ503649','perm_id':911411084,'symbol':'PFE'}
  o=classify_order(order,[],account='DUQ503649',environment='PAPER',external_evidence=True)
  self.assertEqual(o['ownership'],'MANUAL_EXTERNAL');self.assertFalse(o['may_modify']);self.assertEqual(exposure_snapshot([order],[{'symbol':'AAPL'}])['symbols'],['AAPL','PFE'])
  self.assertEqual(classify_order(order,[],account='OTHER',environment='PAPER',external_evidence=True)['ownership'],'UNKNOWN')
  a=occurrence_scope({'account_id':'x','event_id':'state-account-1'},source_id='legacy');b=occurrence_scope({'account_id':'DUQ503649','event_id':'state-account-1'},source_id='live',environment='PAPER',run_id='r1');self.assertNotEqual(a,b);self.assertEqual(a['scope'],'LEGACY_SCOPE')
 def test_safety_gate_never_resumes_unknown_or_paused(self):
  self.healthy();m=self.co.snapshot();facts={'maintenance':False,'manifest_approved':True,'duplicate_or_unknown':False,'reconciled':True,'identity_verified':True,'ownership_verified':True,'risk_allowed':True,'trading_paused':False,'delivery_paused':False}
  self.assertTrue(safety_gate('ORDER_SUBMISSION_ALLOWED',m,facts)['allowed'])
  self.assertFalse(safety_gate('ORDER_SUBMISSION_ALLOWED',m,{**facts,'trading_paused':True})['allowed'])
  self.assertFalse(safety_gate('FEISHU_SEND_ALLOWED',m,{**facts,'duplicate_or_unknown':True})['allowed'])
  self.assertFalse(safety_gate('ORDER_SUBMISSION_ALLOWED',m,{})['allowed'])
 def test_state_machine_fault_matrix(self):
  cases={
   'startup_no_network':('NETWORK','OFFLINE'),
   'normal_disconnect':('NETWORK','OFFLINE'),
   'short_disconnect':('NETWORK','OFFLINE'),
   'long_disconnect':('NETWORK','OFFLINE'),
   'ibkr_only':('IBKR_CONNECTION','OFFLINE'),
   'feishu_only':('FEISHU','OFFLINE'),
   'ibkr_back_feishu_off':('FEISHU','OFFLINE'),
   'feishu_back_ibkr_off':('IBKR_CONNECTION','OFFLINE'),
   'socket_back_market_stale':('MARKET_DATA','DEGRADED'),
   'manual_order_arrival':('ORDERS','RECOVERING'),
   'position_change':('POSITIONS','RECOVERING'),
   'backlog_evaluation':('EXECUTIONS','RECOVERING'),
  }
  for scenario,(module,state) in cases.items():
   with self.subTest(scenario=scenario):
    self.healthy();self.co.observe(module,state,freshness='STALE',reason=scenario)
    snapshot=self.co.snapshot();self.assertEqual(snapshot['DATABASE']['state'],'HEALTHY')
    self.assertNotEqual(snapshot['STRATEGY' if module!='FEISHU' else 'DELIVERY']['state'],'HEALTHY') if module!='EXECUTIONS' else self.assertNotEqual(snapshot['ORDER_SUBMISSION']['state'],'HEALTHY')
    self.assertEqual(self.co.uncertainties(),[])
 def test_manual_reconciliation_does_not_hide_exposure(self):
  from trading.audit import AuditLog
  audit=AuditLog(Path(self.temp.name)/'audit.sqlite3')
  order={'order_id':1,'perm_id':123,'account':'DUQ503649','verified_account':'DUQ503649','environment':'PAPER','external_evidence':True,'symbol':'PFE','status':'PreSubmitted','remaining':8,'quantity':8}
  audit.reconcile([order],[],[])
  self.assertFalse(audit.has_unresolved_external_orders())
  self.assertEqual(len(audit.broker_exposure()),1)
 def test_network_online_does_not_restore_stale_subtrees(self):
  self.healthy();self.co.observe('NETWORK','OFFLINE');self.co.observe('NETWORK','HEALTHY',freshness='FRESH')
  restart=RecoveryCoordinator(self.path,clock=lambda:self.time[0]);s=restart.snapshot()
  self.assertNotEqual(s['IBKR_CONNECTION']['state'],'HEALTHY');self.assertNotEqual(s['STRATEGY']['state'],'HEALTHY')
  with closing(sqlite3.connect(self.path)) as c:
   self.assertGreater(c.execute("SELECT count(*) FROM module_events WHERE payload LIKE '%Invalidated by NETWORK%'").fetchone()[0],0)
 def test_legacy_protection_reference_requires_exact_scoped_source(self):
  order={'account':'DUQ503649','perm_id':911411084,'symbol':'PFE','order_ref':'protect-pfe-20260710010237229135'}
  binding={'account':'DUQ503649','environment':'PAPER','perm_id':911411084,'strategy':'position_protection','intent_id':order['order_ref'],'source_id':'immutable-repair-execute-evidence'}
  self.assertEqual(classify_order(order,[binding],account='DUQ503649',environment='PAPER')['ownership'],'SYSTEM_OWNED')
  self.assertEqual(classify_order(order,[{**binding,'source_id':None}],account='DUQ503649',environment='PAPER')['ownership'],'UNKNOWN')
 def test_production_gate_checks_persisted_account_scope(self):
  from unittest.mock import patch
  import time
  from trading.production_guard import module_gate
  root=Path(self.temp.name)/'production';runtime=root/'runtime'
  store=RecoveryCoordinator(runtime/'recovery.sqlite3',clock=time.time)
  for name in MODULE_DEPENDENCIES:store.observe(name,'HEALTHY',freshness='FRESH')
  store.observe('ACCOUNT','HEALTHY',freshness='FRESH',account='DUQ503649',environment='PAPER')
  code=root/'code';(code/'.git').mkdir(parents=True)
  manifest={'ready':True,'commit':'verified','branch':'production','workspace':str(code),'state_root':str(root),'migration_verified':True,'account':'DUQ503649','environment':'PAPER','safety':{'identity_verified':True,'ownership_verified':True,'risk_allowed':True,'reconciled':True}}
  (root/'production.json').write_text(json.dumps(manifest))
  with patch('trading.production_guard.CODE_ROOT',code),patch('trading.production_guard.PRODUCTION_WORKSPACE',code),patch('trading.production_guard.RUNTIME_ROOT',runtime),patch('trading.production_guard.STATE_ROOT',root),patch('trading.production_guard.context',return_value={'commit':'verified','branch':'production'}):
   self.assertTrue(module_gate('ORDER_SUBMISSION_ALLOWED',duplicate_or_unknown=False)['allowed'])
   for key,bad in [('workspace','/wrong'),('state_root','/wrong'),('environment','LIVE'),('migration_verified',False)]:
    (root/'production.json').write_text(json.dumps({**manifest,key:bad}))
    self.assertFalse(module_gate('ORDER_SUBMISSION_ALLOWED',duplicate_or_unknown=False)['allowed'],key)
   (root/'production.json').write_text(json.dumps(manifest))
   store.observe('ACCOUNT','HEALTHY',freshness='FRESH',account='DU123',environment='PAPER')
   self.assertFalse(module_gate('ORDER_SUBMISSION_ALLOWED',duplicate_or_unknown=False)['allowed'])
