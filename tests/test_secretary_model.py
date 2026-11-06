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
