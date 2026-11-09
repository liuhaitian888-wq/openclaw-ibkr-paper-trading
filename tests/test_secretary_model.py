import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from reporting.secretary_model import analyze

class SecretaryModelTests(unittest.TestCase):
    def fixture(self,root,body):
        p=root/'codex-fixture';p.write_text('#!/usr/bin/env python3\n'+body);p.chmod(0o700);return str(p)
    def test_public_output_usage_only_and_no_private_reasoning_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            events=[{'type':'item.completed','item':{'type':'reasoning','text':'private fixture'}},
                    {'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'summary':'public','tools':[]})}},
                    {'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]
            binary=self.fixture(root,'import json\n'+'\n'.join('print('+repr(json.dumps(e))+')' for e in events))
            result,usage=analyze('fixture',codex=binary,codex_home=root,empty_dir=root)
            self.assertEqual(result['summary'],'public');self.assertEqual(usage['input_tokens'],10)
            self.assertNotIn('private fixture',str(result))
    def test_unexpected_actual_tool_execution_event_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=self.fixture(root,'print(\'{"type":"item.completed","item":{"type":"command_execution"}}\')')
            with self.assertRaises(RuntimeError):analyze('fixture',codex=binary,codex_home=root,empty_dir=root)
    def test_timeout_bounds_owned_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=self.fixture(root,'import time\ntime.sleep(30)')
            with self.assertRaises(subprocess.TimeoutExpired):analyze('fixture',codex=binary,codex_home=root,empty_dir=root,timeout=1)
    def test_cloud_oauth_forces_auth_and_disables_tools_and_provider_retries(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            body='''import os,sys,json
assert 'forced_login_method="chatgpt"' in sys.argv
assert 'model_provider="secretary_oauth"' in sys.argv
assert 'model_providers.secretary_oauth.request_max_retries=0' in sys.argv
assert 'model_providers.secretary_oauth.stream_max_retries=0' in sys.argv
assert 'apps' in sys.argv and 'computer_use' in sys.argv
assert not any(k in os.environ for k in ('OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN'))
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'summary':'oauth fixture','tools':[]})}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
'''
            binary=self.fixture(root,body)
            with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture','CODEX_API_KEY':'fixture','CODEX_ACCESS_TOKEN':'fixture'}):
                result,usage=analyze('fixture JSON',codex=binary,codex_home=root,empty_dir=root,force_chatgpt=True)
            self.assertEqual(result['summary'],'oauth fixture')

    def test_exact_pre_turn_disabled_host_notice_requires_successful_cloud_turn(self):
        from reporting.secretary_model import CODE_MODE_DISABLED_NOTICE
        for mode in ('success','after_start','other_error','no_completion','mac'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                notice={'type':'item.completed','item':{'type':'error','message':CODE_MODE_DISABLED_NOTICE if mode!='other_error' else 'real model failure'}}
                start={'type':'turn.started'}
                events=([start,notice] if mode=='after_start' else [notice,start])
                events.append({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'summary':'ok','tools':[]})}})
                if mode!='no_completion':events.append({'type':'turn.completed','usage':{'output_tokens':2}})
                binary=self.fixture(root,'\n'.join('print('+repr(json.dumps(e))+')' for e in events))
                if mode=='success':
                    result,usage=analyze('fixture',codex=binary,codex_home=root,empty_dir=root,force_chatgpt=True)
                    self.assertEqual(usage['startup_notices'],['CODE_MODE_DISABLED'])
                else:
                    with self.assertRaises(RuntimeError):analyze('fixture',codex=binary,codex_home=root,empty_dir=root,force_chatgpt=mode!='mac')
