import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class SecretScanStopTests(unittest.TestCase):
    def run_hook(self, scanner_exit):
        path=Path(__file__).resolve().parents[1]/'.codex/hooks/secret_scan_stop.py'
        spec=importlib.util.spec_from_file_location('secret_scan_stop',path)
        hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'.gitleaksignore').write_text('receipt.json:generic-api-key:2\n')
            (root/'receipt.json').write_text('{"source_sha256":"documented-placeholder"}')
            (root/'untracked.txt').write_text('synthetic scan input')
            def run(cmd,cwd):
                if cmd[:2]==['git','rev-parse']:out=str(root)+'\n'
                elif cmd[:2]==['git','status']:out='?? untracked.txt\n'
                elif cmd==['git','ls-files']:out='.gitleaksignore\nreceipt.json\n'
                elif cmd[:2]==['git','ls-files']:out='untracked.txt\n'
                else:
                    self.assertEqual(cmd[cmd.index('--source')+1],'.')
                    self.assertEqual(cwd.name,'scan')
                    self.assertEqual((cwd/'.gitleaksignore').read_text(),'receipt.json:generic-api-key:2\n')
                    self.assertTrue((cwd/'receipt.json').is_file())
                    self.assertTrue((cwd/'untracked.txt').is_file())
                    self.assertIn('--redact',cmd)
                    return subprocess.CompletedProcess(cmd,scanner_exit,'','leaks found: 1 [REDACTED]' if scanner_exit else '')
                return subprocess.CompletedProcess(cmd,0,out,'')
            result=io.StringIO()
            with patch.object(hook,'run',side_effect=run),patch.object(hook.shutil,'which',return_value='gitleaks'),patch.object(hook.sys,'stdin',io.StringIO(json.dumps({'cwd':str(root)}))),contextlib.redirect_stdout(result),patch.dict(hook.os.environ,{'CODEX_SECRET_SCAN_DISABLE':'0'}):
                hook.main()
            return json.loads(result.getvalue())

    def test_relative_snapshot_keeps_exact_documented_ignores(self):
        self.assertTrue(self.run_hook(0)['continue'])

    def test_other_scanner_findings_still_block(self):
        result=self.run_hook(1)
        self.assertEqual(result['decision'],'block')
        self.assertIn('leaks found: 1 [REDACTED]',result['reason'])
