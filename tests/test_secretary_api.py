from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.secretary_api import analyze,ModelAPIError,credential,MODEL
from reporting.health import dependency_registry
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize,claim,checkpoint
from ops.cloud.secretary_rpc import dispatch
from scripts.run_secretary_bridge import execute

class ResponsesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.key=self.root/'key';self.key.write_text('sk-'+'fixture_'*5);self.key.chmod(0o600)
  self.receipt=self.root/'receipt.json';self.calls=[];self.closed=False
 def transport(self,data=None,status=200,fail=False):
  outer=self
  class Conn:
   def request(self,*args,**kw):
    outer.calls.append((args,kw))
    if fail:raise TimeoutError('untrusted secret details')
   def getresponse(self):return self
   def read(self,n):return json.dumps(data or dict(id='resp_fixture',model=MODEL,status='completed',output=[dict(type='reasoning',private='omit'),dict(type='message',role='assistant',content=[dict(type='output_text',text=json.dumps(dict(summary='在，云端回复。',tools=[])))])],usage=dict(input_tokens=10,output_tokens=20))).encode()
   def close(self):outer.closed=True
  c=Conn();c.status=status;return lambda:c
 def invoke(self,**kw):return analyze('Return JSON',key_path=self.key,receipt_path=self.receipt,connection_factory=self.transport(**kw))
 def test_low_responses_one_call_store_false_no_tools_and_private_receipt(self):
  result,usage=self.invoke();self.assertIn('云端',result['summary']);self.assertTrue(self.closed)
  args,kw=self.calls[0];self.assertEqual(args[:2],('POST','/v1/responses'))
  payload=json.loads(kw['body']);self.assertEqual(payload['reasoning'],{'effort':'low'});self.assertFalse(payload['store']);self.assertNotIn('tools',payload)
  saved=json.loads(self.receipt.read_text());self.assertEqual(saved['state'],'ACKNOWLEDGED');self.assertNotIn('private',self.receipt.read_text());self.assertNotIn(self.key.read_text(),self.receipt.read_text())
  self.assertEqual(self.receipt.stat().st_mode&0o077,0)
  with self.assertRaises(ModelAPIError):self.invoke()
  self.assertEqual(len(self.calls),1)
 def test_timeout_and_auth_rejection_are_durable_unknown_without_retry(self):
  for options in ({'fail':True},{'status':401},{'status':429},{'status':302}):
   with self.subTest(options=options):
    self.receipt=self.root/(str(len(self.calls))+'.json')
    with self.assertRaises(ModelAPIError) as e:self.invoke(**options)
    self.assertNotIn('untrusted',str(e.exception));self.assertTrue(self.closed)
    self.assertEqual(json.loads(self.receipt.read_text())['state'],'UNKNOWN')
    count=len(self.calls)
    with self.assertRaises(ModelAPIError):self.invoke()
    self.assertEqual(len(self.calls),count)
 def test_incomplete_and_native_tool_outputs_are_not_success(self):
  for output,status in [([], 'incomplete'),([{'type':'function_call'}],'completed')]:
   self.receipt=self.root/(status+'.json')
   with self.assertRaises(ModelAPIError):self.invoke(data=dict(id='resp_fixture',model=MODEL,status=status,output=output))
   self.assertEqual(json.loads(self.receipt.read_text())['state'],'UNKNOWN')
 def test_secret_permissions_and_symlink_fail_before_network(self):
  self.key.chmod(0o644)
  with self.assertRaises(PermissionError):self.invoke()
  self.assertEqual(self.calls,[])
  self.key.chmod(0o600);link=self.root/'symlink';link.symlink_to(self.key)
  with self.assertRaises(OSError):credential(link)
 def test_cloud_executor_never_calls_mac_rpc_or_subprocess(self):
  calls=[]
  def rpc(req):calls.append(req);return {'state':'SUCCEEDED'}
  with patch('scripts.run_secretary_bridge.subprocess.run',side_effect=AssertionError('Mac dependency')):
   result=execute(dict(run='r',payload={'text':'在吗'},model=MODEL),dict(codex=None,codex_home=None,empty_dir=None),invoke=rpc,inference=lambda *a,**k:({'summary':'在','tools':[]},{}),cloud_only=True)
  self.assertEqual(result['state'],'SUCCEEDED');self.assertIn('OpenAI Responses',calls[-1]['result']['source'])
 def test_owner_policy_prevents_old_mac_model_claim(self):
  with patch('ops.cloud.secretary_rpc.reconcile_replies'),patch('reporting.secretary_controls.pending_controls',return_value=[]),patch('ops.cloud.secretary_rpc.claim') as reserve:
   result=dispatch(self.root,{'action':'poll'},{},{'model_owner':'cloud_api','receiver_owner':'cloud'},caller='mac_bridge')
  reserve.assert_not_called();self.assertIsNone(result['job'])
 def test_cloud_registry_requires_credential_without_changing_trade_permission(self):
  self.assertEqual(dependency_registry({'SECRETARY_MODEL':{'provider':'openai_responses'}})['SECRETARY_MODEL'],('NETWORK','SECRETARY_API_CREDENTIAL'))
  self.assertEqual(dependency_registry({})['SECRETARY_MODEL'],('NETWORK',))
 def test_legacy_ready_checkpoint_is_not_resumed_by_new_owner(self):
  a=SecretaryArchive(self.root/'a.sqlite3',clock=lambda:100);initialize(a)
  a.append('q','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'old'})
  j=claim(a,model=MODEL,now=100);checkpoint(a,j['run'],dict(turn=1,step=0,transcript=[],usage=[]))
  self.assertIsNone(claim(a,model=MODEL,now=200,resume_after=150))
  with closing(a.connect()) as c:self.assertEqual(c.execute('select state from secretary_runs').fetchone()[0],'STARTED')

 def test_receipt_ack_is_owner_specific_and_not_execution_confirmation(self):
  from reporting.secretary_queue import acknowledgement
  self.assertIn('收到',acknowledgement('cloud_api'))
  self.assertNotIn('已开始',acknowledgement('cloud_api'))
  self.assertNotIn('Mac',acknowledgement('mac_bridge'))
