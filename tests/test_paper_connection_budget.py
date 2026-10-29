import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from trading.paper_safety_monitor import PaperSafetyMonitor, ENDS
from ops.cloud.paper_safety_watch import gateway_generation

class ConnectionBudgetTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.now=1000
 def monitor(self):
  return PaperSafetyMonitor(self.root/'audit.db',self.root/'recovery.db',symbols=['BAC'],required_bars=3,clock=lambda:self.now)
 def test_restart_and_elapsed_time_never_replenish_same_failure(self):
  for delay in (30,60,120,300):
   m=self.monitor();self.assertTrue(m.admit_connection('204045:123'))
   self.assertFalse(m.admit_connection('204045:123'));self.now+=delay
  self.now+=86400
  m=self.monitor();self.assertFalse(m.admit_connection('204045:123'))
  self.assertFalse(m.admit_connection(None))
  self.assertTrue(m.admit_connection('204046:456'))
  self.assertEqual(m.state['connection_recovery']['attempts'],1)
 def test_api_ready_transition_rearms_once_per_process_after_cooldown(self):
  for delay in (30,60,120,300):
   m=self.monitor();self.assertTrue(m.admit_connection('same',api_listening=False));self.now+=delay
  m=self.monitor();self.assertTrue(m.admit_connection('same',api_listening=True))
  self.assertEqual(m.state['connection_recovery']['rearm_reason'],'API_LISTENER_BECAME_READY_ONCE')
  for delay in (30,60,120):
   self.now+=delay;m=self.monitor();self.assertTrue(m.admit_connection('same',api_listening=True))
  self.now+=300;m=self.monitor();self.assertFalse(m.admit_connection('same',api_listening=False))
  self.assertFalse(m.admit_connection('same',api_listening=True))
  self.now+=86400;self.assertFalse(self.monitor().admit_connection('same',api_listening=True))
 def test_listener_parser_is_passive_loopback_only(self):
  from ops.cloud.paper_safety_watch import api_listener_ready
  with patch('ops.cloud.paper_safety_watch.Path.read_text',return_value='header\n0: 0100007F:0FA2 00000000:0000 0A'):
   self.assertTrue(api_listener_ready())
  with patch('ops.cloud.paper_safety_watch.Path.read_text',return_value='header\n0: 00000000:0FA2 00000000:0000 0A'):
   self.assertFalse(api_listener_ready())
 def test_changed_gateway_still_requires_cooldown(self):
  m=self.monitor()
  for delay in (30,60,120):
   self.assertTrue(m.admit_connection('old'));self.now+=delay
  self.assertTrue(m.admit_connection('old'))
  self.assertFalse(m.admit_connection('new'))
  self.now+=300;self.assertTrue(m.admit_connection('new'))
 def test_socket_alone_or_partial_readback_cannot_reset_budget(self):
  m=self.monitor();m.admit_connection('old');started=self.now
  self.now+=60
  m.state.update(connected=True,identity=True,upstream_connected=True,last_server_reply=self.now,dirty=False)
  self.assertFalse(m.validate_connection(started))
  m.state['ends']=list(ENDS)
  self.assertTrue(m.validate_connection(started))
  self.assertEqual(self.monitor().state['connection_recovery']['attempts'],0)
 def test_short_or_stale_or_identity_failure_cannot_reset(self):
  for field,value in (('identity',False),('upstream_connected',False),('dirty',True),('last_server_reply',0)):
   m=self.monitor();m.state.update(connected=True,identity=True,upstream_connected=True,last_server_reply=self.now,dirty=False,ends=list(ENDS));m.state[field]=value
   self.assertFalse(m.validate_connection(self.now-60))
  m=self.monitor();self.assertFalse(m.validate_connection(self.now))
 @patch('ops.cloud.paper_safety_watch.subprocess.check_output',return_value='0\n')
 def test_missing_gateway_never_becomes_rearm_condition(self,command):
  self.assertIsNone(gateway_generation())
