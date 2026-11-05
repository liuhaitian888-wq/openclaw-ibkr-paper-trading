from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from ops.cloud.gateway_automater import validate_deployment,run_owned

class GatewayAutomaterTests(unittest.TestCase):
 def test_unapproved_or_changed_manifest_never_reads_credentials_or_launches(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);(r/'runtime').mkdir();(r/'runtime/gateway-automater-deployment.json').write_text(json.dumps({'approved':False}))
   with self.assertRaises(PermissionError):validate_deployment(r,{},home=r)
 def test_group_readable_credentials_rejected_before_release_access(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);(r/'runtime').mkdir();actual={k:'verified' for k in ('commit','branch','code_root','state_root')};d={'approved':True,'environment':'PAPER','grants_trading_permission':False,**actual}
   (r/'runtime/gateway-automater-deployment.json').write_text(json.dumps(d))
   p=r/'.config/openclaw';p.mkdir(parents=True);f=p/'ibautomater-credentials.json';f.write_text('{}');f.chmod(0o644)
   with self.assertRaises(PermissionError):validate_deployment(r,actual,home=r)
 def test_stop_targets_owned_handle_with_bounded_escalation(self):
  process=Mock();process.poll.return_value=None;process.wait.side_effect=[__import__('subprocess').TimeoutExpired('owned',30),0]
  stop=threading.Event();stop.set()
  with patch('ops.cloud.gateway_automater.subprocess.Popen',return_value=process):run_owned(['owned'],{},stop_event=stop)
  process.terminate.assert_called_once();process.kill.assert_called_once()
 def test_upstream_launcher_does_not_kill_peers_or_replace_display(self):
  root=Path(__file__).resolve().parents[1]/'ops/ibautomater/upstream'
  # These are integration safety boundaries, not the UI implementation contract.
  for p in [root/'QuantConnect.IBAutomater/IBAutomater.sh',root/'QuantConnect.IBAutomater/IBAutomater.cs']:
   self.assertNotIn('pkill',p.read_text())
  java=(root/'java/IBAutomater/src/ibautomater/WindowEventListener.java').read_text()
  self.assertNotIn('readOnlyApi.setSelected(false)',java)
  self.assertNotIn('checkBox.setSelected(true)',java[java.index('String bypassOrderPrecautionsText'):java.index('String autoRestartText')])
