from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from ops.cloud.shadow_market_health import ShadowMarketHealth
from trading.symbol_health import classify_symbol, session_for_symbol, symbol_market_permission

class ShadowMarketHealthTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.prod=self.root/'production';self.prod.mkdir();(self.prod/'runtime').mkdir()
  self.source=self.prod/'runtime/recovery.sqlite3';self.output=self.root/'shadow'
  self.state=dict(connected=True,identity=True,quotes={},bars={},retries=0,collision_since=None,
   market_errors={'PFE':dict(code=10197,details='competing session',observed_at=1000)},
   orders={'1':dict(symbol='PFE',remaining=8,aux_price=23.01,status='PreSubmitted',perm_id=911411084)})
  with closing(sqlite3.connect(self.source)) as c,c:
   c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)');c.execute('INSERT INTO paper_safety_state VALUES (1,?)',(json.dumps(self.state),))
  (self.prod/'paper.env').write_text('TRADING_KILL_SWITCH=true\nALLOW_PAPER_TRANSMIT=false\n')
 def digests(self):return {str(p.relative_to(self.prod)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.prod.rglob('*') if p.is_file()}
 def test_shadow_has_no_broker_mail_service_or_production_state_side_effect(self):
  before=self.digests()
  with patch('smtplib.SMTP',side_effect=AssertionError('Real mail forbidden')),patch('subprocess.Popen',side_effect=AssertionError('Service or process forbidden')),patch('ibapi.client.EClient.reqMktData',side_effect=AssertionError('Broker request forbidden')),patch('ibapi.client.EClient.placeOrder',side_effect=AssertionError('Order forbidden')),patch('ibapi.client.EClient.cancelOrder',side_effect=AssertionError('Protection mutation forbidden')),patch('ops.cloud.shadow_market_health.session_for_symbol',return_value='REGULAR'):
   runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
   reports=[runner.step(now=t) for t in (1000,1061,1122)]
  self.assertEqual(before,self.digests())
  self.assertTrue(any(r['would_execute'] for r in reports));self.assertTrue(reports[-1]['simulated_notifications'])
  self.assertEqual(reports[-1]['diagnoses']['PFE']['code'],10197)
  self.assertIsNone(runner.policy.store.claim())
  with closing(runner.policy.store.connect()) as c:
   self.assertEqual(c.execute('SELECT DISTINCT status FROM notification_outbox').fetchall(),[('SHADOW_ONLY',)])
  self.assertTrue(all(r['broker_requests_sent']==0 and r['real_alerts_sent']==0 and not r['grants_trading_permission'] for r in reports))
  self.assertEqual((self.output/'shadow.sqlite3').stat().st_mode&0o077,0)
 def test_unknown_calendar_keeps_observation_and_blocks_trade(self):
  with patch('trading.market_session._calendar_status_from_package',return_value=None),patch('trading.market_session._calendar_status_from_local_file',return_value=None):
   from datetime import datetime
   now=datetime.fromisoformat('2026-10-28T16:00:00+00:00').timestamp()
   self.assertEqual(session_for_symbol(now),'SESSION_UNKNOWN')
   runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod);report=runner.step(now=now)
   self.assertEqual(report['session'],'SESSION_UNKNOWN');self.assertTrue(report['would_execute'])
   health=classify_symbol(dict(data_type=1,bid=29,ask=30,bid_at=now,ask_at=now),now,session=report['session'])
   self.assertEqual(health['status'],'REALTIME_HEALTHY');self.assertFalse(health['allows_realtime'])
   self.assertFalse(symbol_market_permission(dict(health=health,phase='NORMAL',fault_active=False),now)['allowed'])
 def test_shadow_refuses_production_output_or_alias(self):
  for output in (self.prod,self.prod/'diagnostics',self.root):
   with self.assertRaises(ValueError):ShadowMarketHealth(self.source,output,['PFE'],production_root=self.prod)
  self.output.mkdir();(self.output/'shadow.sqlite3').symlink_to(self.source)
  with self.assertRaises(ValueError):ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
 def test_legacy_exhausted_budget_is_simulated_without_fresh_allowance(self):
  self.state.update(retries=30,collision_since=100)
  with closing(sqlite3.connect(self.source)) as c,c:c.execute('UPDATE paper_safety_state SET payload=?',(json.dumps(self.state),))
  before=self.digests()
  runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
  report=runner.step(now=1000)
  self.assertEqual(report['would_execute'][0]['decision']['reason'],'INCIDENT_BUDGET_EXHAUSTED')
  self.assertEqual(before,self.digests())
 def test_simulation_restart_uses_same_budget_and_separate_state(self):
  with patch('ops.cloud.shadow_market_health.session_for_symbol',return_value='REGULAR'):
   for n in range(5):
    runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
    report=runner.step(now=1000+n*300)
   runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
   report=runner.step(now=10000)
  self.assertFalse(report['would_execute'][0]['decision']['allowed'])
  self.assertEqual(runner.policy.lifecycle.snapshot('PFE')['attempts'],4)

 def test_wrong_production_root_is_rejected_before_output_creation(self):
  wrong=self.root/'wrong';wrong.mkdir()
  with self.assertRaises(ValueError):ShadowMarketHealth(self.source,self.output,['PFE'],production_root=wrong)
  self.assertFalse(self.output.exists())
 def test_broken_calendar_still_returns_unknown_without_stopping_observation(self):
  with patch('trading.market_session.current_market_session',side_effect=ValueError('Invalid untrusted calendar')):
   self.assertEqual(session_for_symbol(1000),'SESSION_UNKNOWN')
   runner=ShadowMarketHealth(self.source,self.output,['PFE'],production_root=self.prod)
   self.assertEqual(runner.step(now=1000)['session'],'SESSION_UNKNOWN')
