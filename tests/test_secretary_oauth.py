import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reporting.secretary_oauth import oauth_ready,analyze
from reporting.secretary_api import ModelAPIError
from reporting.health import dependency_registry
from reporting.secretary_queue import acknowledgement
from ops.cloud.secretary_cloud_api import policy
from ops.cloud.secretary_rpc import dispatch

class CloudOAuthTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.home=self.root/'secretary-oauth';self.home.mkdir(mode=0o700)
  self.auth=self.home/'auth.json';self.auth.write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'fixture':'not-a-token'}}));self.auth.chmod(0o600)
  (self.root/'secretary-oauth-empty').mkdir()
 def test_only_owned_private_chatgpt_auth_is_accepted(self):
  self.assertTrue(oauth_ready(self.home))
  self.auth.write_text(json.dumps({'auth_mode':'apikey'}))
  with self.assertRaises(PermissionError):oauth_ready(self.home)
  self.auth.chmod(0o644)
  with self.assertRaises(PermissionError):oauth_ready(self.home)
 def test_native_oauth_result_durable_without_copying_token_fields(self):
  receipt=self.root/'receipt.json'
  with patch('reporting.secretary_oauth.codex_analyze',return_value=({'summary':'在，云端OAuth','tools':[]},{'output_tokens':5})) as native:
   result,usage=analyze('JSON please',key_path=self.home,receipt_path=receipt)
   self.assertTrue(native.call_args.kwargs['force_chatgpt']);self.assertEqual(native.call_args.kwargs['codex_home'],self.home)
   self.assertEqual(json.loads(receipt.read_text())['state'],'ACKNOWLEDGED');self.assertNotIn('not-a-token',receipt.read_text())
   with self.assertRaises(ModelAPIError):analyze('JSON please',key_path=self.home,receipt_path=receipt)
   self.assertEqual(native.call_count,1)
 def test_failure_is_unknown_and_never_replayed(self):
  receipt=self.root/'bad.json'
  with patch('reporting.secretary_oauth.codex_analyze',side_effect=RuntimeError('secret details')) as native:
   with self.assertRaises(ModelAPIError) as e:analyze('JSON',key_path=self.home,receipt_path=receipt)
   self.assertNotIn('secret',str(e.exception));self.assertEqual(json.loads(receipt.read_text())['state'],'UNKNOWN')
   with self.assertRaises(ModelAPIError):analyze('JSON',key_path=self.home,receipt_path=receipt)
   self.assertEqual(native.call_count,1)
 def test_oauth_owner_policy_and_health_dependency(self):
  (self.root/'runtime').mkdir()
  (self.root/'runtime/secretary-policy.json').write_text(json.dumps(dict(approved=True,grants_trading_permission=False,model_owner='cloud_oauth',model='gpt-6.1-sol',reasoning_effort='low',model_owner_since=123)))
  self.assertEqual(policy(self.root,'cloud_oauth')['model_owner'],'cloud_oauth')
  with self.assertRaises(PermissionError):policy(self.root)
  self.assertEqual(dependency_registry({'SECRETARY_MODEL':{'provider':'codex_oauth'}})['SECRETARY_MODEL'],('NETWORK','SECRETARY_OAUTH'))
  self.assertNotIn('Mac',acknowledgement('cloud_oauth'))
 def test_old_mac_cannot_claim_oauth_tasks(self):
  with patch('ops.cloud.secretary_rpc.reconcile_replies'),patch('reporting.secretary_controls.pending_controls',return_value=[]),patch('ops.cloud.secretary_rpc.claim') as reserve:
   result=dispatch(self.root,{'action':'poll'},{},{'model_owner':'cloud_oauth','receiver_owner':'cloud'},caller='mac_bridge')
  self.assertIsNone(result['job']);reserve.assert_not_called()
