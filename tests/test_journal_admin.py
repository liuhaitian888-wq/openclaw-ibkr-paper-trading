from pathlib import Path
import tempfile
import unittest

from ops.cloud.journal_admin import dispatch
from reporting.journal_rotation import append_jsonl, JournalEvidenceError
from reporting.journal_backup import backup_journal
from test_journal_recovery import event, interrupt


class JournalAdminTests(unittest.TestCase):
    def test_recover_requires_paused_maintenance_disarmed_and_matching_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'reports/order_rejections/history.jsonl'
            append_jsonl(p,event('old'));interrupt(p,'receipt')
            plan=dispatch('inspect',root,journal='order_rejections')
            kwargs=dict(journal='order_rejections',token=plan['approval_token'])
            with self.assertRaises(PermissionError):dispatch('recover',root,**kwargs)
            (root/'PAUSED').touch();(root/'runtime').mkdir();(root/'runtime/MAINTENANCE').touch()
            (root/'runtime/EMAIL_ALERTS_ARMED').touch()
            with self.assertRaises(PermissionError):dispatch('recover',root,**kwargs)
            (root/'runtime/EMAIL_ALERTS_ARMED').unlink()
            with self.assertRaises(JournalEvidenceError):dispatch('recover',root,journal='order_rejections',token='0'*64)
            self.assertEqual(dispatch('recover',root,**kwargs)['status'],'COMPLETED')
            self.assertFalse((root/'runtime/recovery.sqlite3').exists())

    def test_restore_is_always_isolated_and_rejects_symlink_or_escaped_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'reports/order_rejections/history.jsonl'
            append_jsonl(p,event('old'));backup=root/'backups/source'
            result=backup_journal(p,backup)
            kwargs=dict(backup=backup,token=result['approval_token'])
            for target in (root/'reports/restored',root/'monitoring-tests/../escape'):
                with self.assertRaises(ValueError):dispatch('restore',root,target=target,**kwargs)
            (root/'monitoring-tests').mkdir();(root/'monitoring-tests/link').symlink_to(root/'reports',target_is_directory=True)
            with self.assertRaises(ValueError):dispatch('restore',root,target=root/'monitoring-tests/link/restore',**kwargs)
            restored=dispatch('restore',root,target=root/'monitoring-tests/candidate',**kwargs)
            self.assertFalse(restored['production_activated'])

    def test_isolation_root_itself_cannot_be_redirected_by_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'reports/order_rejections/history.jsonl'
            append_jsonl(p,event('old'));backup=root/'backups/source'
            result=backup_journal(p,backup)
            elsewhere=root/'elsewhere';elsewhere.mkdir()
            (root/'monitoring-tests').symlink_to(elsewhere,target_is_directory=True)
            with self.assertRaises(ValueError):
                dispatch('restore',root,backup=backup,target=root/'monitoring-tests/candidate',token=result['approval_token'])
            self.assertEqual(list(elsewhere.iterdir()),[])
