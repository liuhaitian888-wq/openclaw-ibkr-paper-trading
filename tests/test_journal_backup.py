import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.journal_backup import backup_journal, inspect_backup, restore_journal
from reporting.journal_recovery import inspect_rotation, recover_rotation
from reporting import journal_rotation as journal
from test_journal_recovery import event, interrupt


class JournalBackupTests(unittest.TestCase):
    def test_restored_candidate_preserves_original_bytes_and_rebinds_only_file_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root/'source/history.jsonl'
            journal.append_jsonl(p, event('old')); journal.rotate_journal(p)
            journal.append_jsonl(p, event('new'))
            result = backup_journal(p, root/'backup')
            manifest = inspect_backup(root/'backup')['manifest']
            restored = restore_journal(root/'backup', root/'restore', result['approval_token'])
            active = Path(restored['journal'])
            self.assertEqual(active.read_bytes(), p.read_bytes())
            self.assertNotEqual(journal.inode(active), journal.inode(p))
            self.assertFalse(restored['cursor_updated']); self.assertFalse(restored['production_activated'])
            for item in manifest['files']:
                self.assertEqual((root/'restore/originals'/item['path']).read_bytes(),
                                 (root/'backup/payload'/item['path']).read_bytes())
            journal.verify_active(active)
            journal.append_jsonl(active, event('after-restore'))
            journal.rotate_journal(active)
            self.assertEqual(len(journal.receipts(active)), 2)
            with self.assertRaises(journal.JournalEvidenceError):
                restore_journal(root/'backup', root/'restore', result['approval_token'])

    def test_pending_backup_can_be_reconciled_only_in_isolated_candidate(self):
        for phase in ('rename', 'active', 'receipt', 'writer', 'release'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); p = root/'source/history.jsonl'
                journal.append_jsonl(p, event('unread')); interrupt(p, phase)
                result = backup_journal(p, root/'backup')
                restored = restore_journal(root/'backup', root/'restore', result['approval_token'])
                active = Path(restored['journal'])
                plan = inspect_rotation(active); recover_rotation(active, plan['approval_token'])
                journal.append_jsonl(active, event('current'))
                self.assertTrue(journal._paths(p)[2].exists())
                self.assertEqual(len(journal.receipts(active)), 1)

    def test_tampering_path_escape_symlink_and_stale_token_fail_before_restore(self):
        for failure in ('tamper', 'escape', 'symlink', 'token'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); p = root/'source/history.jsonl'
                journal.append_jsonl(p, event('old'))
                result = backup_journal(p, root/'backup')
                target = root/'restore'; copied = root/'backup/payload/history.jsonl'
                if failure == 'tamper': copied.write_text('changed\n')
                elif failure == 'escape':
                    m = root/'backup/manifest.json'; value = json.loads(m.read_text())
                    value['files'][0]['path'] = '../outside'; m.write_text(json.dumps(value))
                elif failure == 'symlink':
                    outside = root/'outside'; copied.rename(outside); copied.symlink_to(outside)
                else: result['approval_token'] = '0'*64
                with self.assertRaises(journal.JournalEvidenceError):
                    restore_journal(root/'backup', target, result['approval_token'])
                self.assertFalse(target.exists())

    def test_failed_copy_has_no_completion_manifest_and_cannot_be_restored(self):
        import reporting.journal_backup as backup
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root/'source/history.jsonl'
            journal.append_jsonl(p, event('old'))
            with patch.object(backup.shutil, 'copyfileobj', side_effect=OSError('synthetic disk failure')):
                with self.assertRaises(OSError): backup_journal(p, root/'backup')
            self.assertFalse((root/'backup/manifest.json').exists())
            with self.assertRaises(FileNotFoundError): inspect_backup(root/'backup')

    def test_missing_source_does_not_create_source_or_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root/'source/history.jsonl'
            self.assertEqual(backup_journal(p, root/'backup')['status'], 'MISSING_NO_JOURNAL')
            self.assertFalse(p.parent.exists()); self.assertFalse((root/'backup').exists())

    def test_backup_timer_includes_available_journal_and_marks_missing_sources(self):
        from ops.cloud import backup_state
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); root = home/'.local/state/openclaw'
            p = root/'reports/order_rejections/history.jsonl'
            journal.append_jsonl(p, event('old'))
            with patch.object(Path, 'home', return_value=home), redirect_stdout(io.StringIO()):
                backup_state.main()
            manifest_path = next((root/'backups').glob('*/backup.json'))
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest['journals']['order_rejections']['status'], 'BACKED_UP')
            self.assertEqual(manifest['journals']['position_guard']['status'], 'MISSING_NO_JOURNAL')
            self.assertTrue(all(x['status'] == 'MISSING_NOT_PUBLISHED' for x in manifest['items']))

    def test_shadow_acceptance_is_offline_bounded_and_preserves_unknown_order(self):
        from ops.cloud.shadow_journal_acceptance import run_shadow
        with tempfile.TemporaryDirectory() as tmp:
            summary=run_shadow(Path(tmp)/'isolated')
            self.assertTrue(all(x=='PASS' for x in summary['outcomes'].values()))
            self.assertEqual(summary['attempted_network_connections'],0)
            self.assertFalse(summary['production_cursor_updated'])

    def test_restore_failure_cannot_leave_a_completion_marker(self):
        import reporting.journal_backup as backup
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source/history.jsonl';journal.append_jsonl(p,event('old'))
            result=backup_journal(p,root/'backup');save=backup._save
            def fail(path,value):
                if path.name=='source-manifest.json':raise OSError('Synthetic interrupted metadata')
                return save(path,value)
            with patch.object(backup,'_save',side_effect=fail):
                with self.assertRaises(OSError):restore_journal(root/'backup',root/'restore',result['approval_token'])
            self.assertFalse((root/'restore/restore-map.json').exists())
            self.assertTrue((root/'backup/manifest.json').exists())

    def test_recovery_evidence_without_active_journal_is_still_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source/history.jsonl'
            proof=p.with_name(p.name+'.recovery')/'evidence/plan.json'
            proof.parent.mkdir(parents=True);proof.write_text('{"evidence_only":true}')
            result=backup_journal(p,root/'backup')
            self.assertEqual(result['status'],'BACKED_UP')
            self.assertEqual(inspect_backup(root/'backup')['manifest']['files'][0]['path'],
                             'history.jsonl.recovery/evidence/plan.json')
