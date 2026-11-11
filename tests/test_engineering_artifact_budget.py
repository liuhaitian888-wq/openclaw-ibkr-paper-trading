from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from reporting import storage_policy as budget
from reporting.engineering_patch import prepare, command


def disk(free):
    return SimpleNamespace(f_bavail=int(free*budget.GIB),f_blocks=40*budget.GIB,f_frsize=1)


class ArtifactBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
        (self.root/'runtime/storage-policy.json').write_text(json.dumps(budget.POLICY))

    def test_development_guard_is_before_reserve_children_and_snapshot(self):
        import test_engineering_development as fixture
        case=fixture.DevelopmentTests('test_model_proposal_keeps_provenance_and_cannot_claim_user_native_authority')
        case.setUp();self.addCleanup(case.doCleanups)
        queued=case.enqueue();case.a.finish_run('secretary-run',state='FAILED')
        (case.root/'runtime/storage-policy.json').write_text(json.dumps(budget.POLICY))
        with patch.object(budget.os,'statvfs',return_value=disk(5.5)),patch('reporting.engineering_development.reserve',side_effect=AssertionError('must not reserve')),patch('reporting.engineering_sandbox.capabilities',side_effect=AssertionError('must not start canary')):
            self.assertEqual(case.execute(),'DEFERRED_CAPACITY')
        with closing(case.a.connect()) as c:
            self.assertEqual(c.execute('SELECT state FROM secretary_engineering_tasks WHERE id=?',(queued['task_id'],)).fetchone()[0],'QUEUED')
            self.assertEqual(c.execute('SELECT count(*) FROM secretary_runs').fetchone()[0],1)
        self.assertFalse((case.root/'engineering/development').exists());self.assertEqual(case.calls,0)

    def test_prepare_direct_entry_defers_before_any_file_or_git(self):
        job=self.root/'engineering/development/fixture'
        with patch.object(budget.os,'statvfs',return_value=disk(5.5)),patch('reporting.engineering_patch.command',side_effect=AssertionError('must not copy')):
            with self.assertRaises(OSError):prepare(Path.cwd(),'a'*40,job)
        self.assertFalse(job.exists())

    def test_class_quota_and_incomplete_scan_fail_closed(self):
        with patch.object(budget.os,'statvfs',return_value=disk(20)),patch.object(budget,'usage',return_value=400*budget.MIB):
            self.assertEqual(budget.engineering_preflight(self.root)['state'],'DEFERRED_CLASS_QUOTA')
        with patch.object(budget,'usage',side_effect=TimeoutError):
            self.assertEqual(budget.engineering_preflight(self.root)['state'],'DEFERRED_CAPACITY_UNKNOWN')

    def test_publication_includes_required_backups_and_refuses_over_budget(self):
        for rel in ('runtime/recovery.sqlite3','agent_secretary.sqlite3'):
            (self.root/rel).write_bytes(b'fixture database bytes')
        okay=budget.publication_decision(self.root,input_bytes=38810,source_bundle_bytes=5*budget.MIB,disk=disk(5.5))
        self.assertTrue(okay['allowed']);self.assertEqual(okay['required_backup_bytes'],44)
        bad=budget.publication_decision(self.root,input_bytes=0,source_bundle_bytes=0,extra_bytes=257*budget.MIB,disk=disk(5.5))
        self.assertFalse(bad['allowed']);self.assertGreater(bad['projected_bytes'],256*budget.MIB)
        self.assertFalse(budget.publication_decision(self.root,input_bytes=0,source_bundle_bytes=0,disk=disk(2))['allowed'])
        self.assertEqual((self.root/'runtime/recovery.sqlite3').read_bytes(),b'fixture database bytes')

    def test_archive_writer_hard_file_limit_and_bounded_child_shutdown(self):
        target=self.root/'oversize'
        code='from pathlib import Path;Path('+repr(str(target))+').write_bytes(b"x"*1048576)'
        value=command([sys.executable,'-c',code],cwd=self.root,home=self.root,timeout=3,file_limit=4096)
        self.assertNotEqual(value['exit_code'],0);self.assertLessEqual(target.stat().st_size,4096)
