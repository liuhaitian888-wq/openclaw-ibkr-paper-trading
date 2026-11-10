import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reporting.codex_appserver import argv, run


class NativeAppServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'oauth'; self.home.mkdir(mode=0o700)
        (self.home/'auth.json').write_text('{"auth_mode":"chatgpt"}')
        (self.home/'auth.json').chmod(0o600)
        self.empty = self.root/'empty'; self.empty.mkdir()
        self.records = []; self.children = []
        original = subprocess.Popen
        def owned(*args, **kwargs):
            child = original(*args, **kwargs); self.children.append(child); return child
        self.mock = patch('reporting.codex_appserver.subprocess.Popen', side_effect=owned)
        self.mock.start(); self.addCleanup(self.mock.stop)

    def fake(self, mode='complete'):
        path = self.root/'native-protocol-fixture'
        path.write_text('''#!/usr/bin/env python3
import json,sys,time
MODE=''' + repr(mode) + '''
def send(value):print(json.dumps(value),flush=True)
for line in sys.stdin:
 m=json.loads(line);method=m['method'];identity=m.get('id');p=m.get('params',{})
 if method=='initialize':send({'id':identity,'result':{'userAgent':'fixture'}})
 elif method=='thread/start':
  assert p['sandbox']=='read-only' and p['approvalPolicy']=='never' and p['ephemeral'] is True
  send({'id':identity,'result':{'thread':{'id':'native-thread'},'model':'gpt-6.1-sol','modelProvider':'secretary_oauth','approvalPolicy':'never','sandbox':{'type':'readOnly','networkAccess':False}}})
 elif method=='turn/start':
  assert p['sandboxPolicy']=={'type':'readOnly','networkAccess':False} and p['effort']=='low'
  send({'method':'item/started','params':{'threadId':'native-thread','turnId':'native-turn','item':{'type':'userMessage','content':p['input']}}})
  send({'id':identity,'result':{'turn':{'id':'native-turn','status':'inProgress'}}})
  send({'method':'item/completed','params':{'threadId':'native-thread','turnId':'native-turn','item':{'type':'userMessage','content':p['input']}}})
  if MODE=='hang':time.sleep(30)
  if MODE=='tool':send({'id':100,'method':'item/commandExecution/requestApproval','params':{}});continue
  if MODE=='file':send({'method':'item/started','params':{'threadId':'native-thread','turnId':'native-turn','item':{'type':'fileChange'}}});continue
  tid='other-turn' if MODE=='mismatch' else 'native-turn'
  send({'method':'item/completed','params':{'threadId':'native-thread','turnId':tid,'item':{'type':'agentMessage','text':'{"summary":"数据库检查完成。"}'}}})
  send({'method':'turn/completed','params':{'threadId':'native-thread','turn':{'id':'native-turn','status':'completed'}}})
''')
        path.chmod(0o700)
        return path

    def invoke(self, mode='complete', **kwargs):
        return run({'database_count':4}, home=self.home, empty_dir=self.empty,
            codex=self.fake(mode), record=lambda stage, value:self.records.append((stage,value)), **kwargs)

    def assert_closed(self):
        self.assertEqual(1,len(self.children))
        self.assertIsNotNone(self.children[0].poll())
        self.assertTrue(self.children[0].stdin.closed); self.assertTrue(self.children[0].stdout.closed)

    def test_real_child_native_ids_public_output_and_cleanup(self):
        result=self.invoke()
        self.assertEqual('native-turn',result['turn_id'])
        self.assertEqual(['THREAD_CREATED','TURN_ACCEPTED','TURN_COMPLETED'],[x[0] for x in self.records])
        self.assertEqual({'thread_id':'native-thread','turn_id':'native-turn'},self.records[1][1])
        self.assert_closed()

    def test_native_tool_request_refused_and_completion_identity_must_match(self):
        for mode, expected in [('tool',PermissionError),('file',PermissionError),('mismatch',ValueError)]:
            self.children.clear();self.records.clear()
            with self.assertRaises(expected):self.invoke(mode)
            self.assertNotIn('TURN_COMPLETED',[x[0] for x in self.records]);self.assert_closed()

    def test_hung_native_child_is_bounded_and_owned_pipes_are_closed(self):
        with self.assertRaises(TimeoutError):self.invoke('hang',timeout=1)
        self.assertEqual('TURN_ACCEPTED',self.records[-1][0]);self.assert_closed()

    def test_initialize_only_does_not_create_thread_or_inference(self):
        self.assertEqual({'state':'INITIALIZE_ACKNOWLEDGED','inference':False},self.invoke(handshake_only=True))
        self.assertEqual([],self.records);self.assert_closed()

    def test_thread_probe_uses_empty_home_and_cannot_launch_inference(self):
        home=self.root/'probe-home';home.mkdir(mode=0o700)
        result=run({},home=home,empty_dir=self.empty,codex=self.fake(),
            record=lambda stage,value:self.records.append((stage,value)),probe_thread_only=True)
        self.assertEqual('THREAD_CREATED_NO_TURN',result['state'])
        self.assertEqual(['THREAD_CREATED'],[x[0] for x in self.records]);self.assert_closed()

    def test_config_and_empty_cwd_fail_before_child_and_no_model_native_tools_enabled(self):
        (self.home/'config.toml').write_text('[mcp_servers.arbitrary]\ncommand="unsafe"\n')
        with self.assertRaises(PermissionError):self.invoke()
        self.assertEqual([],self.children)
        (self.home/'config.toml').unlink();(self.empty/'secret').write_text('placeholder')
        with self.assertRaises(PermissionError):self.invoke()
        self.assertEqual([],self.children)
        args=argv('/fixed/codex')
        self.assertIn('shell_tool',args);self.assertIn('code_mode_host',args)
        self.assertIn('model_providers.secretary_oauth.request_max_retries=0',args)
        self.assertNotIn('--yolo',args)
