from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.journal_recovery import inspect_rotation, recover_rotation
from reporting import journal_rotation as journal


def event(key):
    return dict(timestamp='2026-10-27T10:00:00+00:00', local_plan_id=key, symbol='TEST_ONLY')


def interrupt(path, phase):
    save = journal._save
    rename = Path.rename
    unlink = Path.unlink
    open_file = journal.os.open

    def saved(p, value):
        if (phase == 'receipt' and p == journal._paths(path)[1]
                or phase == 'writer' and p == journal._writer_state_path(path)):
            raise OSError('synthetic interrupted commit')
        return save(p, value)

    def opened(p, flags, *args, **kwargs):
        if phase == 'active' and Path(p) == path:
            raise OSError('synthetic interrupted creation')
        return open_file(p, flags, *args, **kwargs)

    def renamed(p, target):
        if phase == 'rename' and p == path:
            raise OSError('synthetic interrupted rename')
        return rename(p, target)

    def unlinked(p, *args, **kwargs):
        if phase == 'release' and p == journal._paths(path)[2]:
            raise OSError('synthetic interrupted release')
        return unlink(p, *args, **kwargs)

    with patch.object(journal, '_save', side_effect=saved), \
            patch.object(journal.os, 'open', side_effect=opened), \
            patch.object(Path, 'rename', renamed), patch.object(Path, 'unlink', unlinked):
        try:
            journal.rotate_journal(path)
        except OSError:
            pass
        else:
            raise AssertionError('Fault injection did not interrupt rotation')


class JournalRecoveryTests(unittest.TestCase):
    def test_each_durable_phase_preserves_unread_tail_and_restart_does_not_replay(self):
        for phase in ('rename', 'active', 'receipt', 'writer', 'release'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)/'history.jsonl'
                store = IncidentStore(Path(tmp)/'shadow.sqlite3')
                reader = IncidentCollector(store)
                journal.append_jsonl(p, event('baseline')); reader.rejections(p)
                journal.append_jsonl(p, event('unread'))
                original = p.read_bytes()
                interrupt(p, phase)
                with self.assertRaises(EvidenceChanged): reader.rejections(p)
                plan = inspect_rotation(p)
                self.assertEqual(recover_rotation(p, plan['approval_token'])['status'], 'COMPLETED')
                self.assertEqual(recover_rotation(p, plan['approval_token'])['status'], 'ALREADY_COMPLETED')
                chain = journal.receipts(p)
                self.assertEqual(len(chain), 1)
                self.assertEqual((journal._paths(p)[3]/chain[0]['archive']).read_bytes(), original)
                journal.append_jsonl(p, event('new'))
                self.assertEqual(reader.rejections(p), 2)
                self.assertEqual(IncidentCollector(IncidentStore(store.path)).rejections(p), 0)
                with closing(store.connect()) as c:
                    self.assertEqual(c.execute('select count(*) from incident_events').fetchone()[0], 2)
                    self.assertEqual(c.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_stale_inspection_and_conflicting_active_data_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'history.jsonl'; journal.append_jsonl(p, event('old'))
            interrupt(p, 'receipt'); plan = inspect_rotation(p)
            p.touch()
            with self.assertRaises(journal.JournalEvidenceError): recover_rotation(p, plan['approval_token'])
            p.write_text('unaccounted data\n')
            with self.assertRaises(journal.JournalEvidenceError): inspect_rotation(p)
            self.assertTrue(journal._paths(p)[2].exists())

    def test_tampered_or_missing_archive_is_not_reconstructed(self):
        for failure in ('tampered', 'missing'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp)/'history.jsonl'; journal.append_jsonl(p, event('old'))
                interrupt(p, 'receipt')
                item = json.loads(journal._paths(p)[2].read_text())
                archive = journal._paths(p)[3]/item['archive']
                if failure == 'tampered': archive.write_bytes(archive.read_bytes().replace(b'old', b'bad'))
                else: archive.rename(archive.with_suffix('.preserved'))
                with self.assertRaises(journal.JournalEvidenceError): inspect_rotation(p)
                self.assertTrue(journal._paths(p)[2].exists())

    def test_second_interruption_requires_fresh_inspection_and_retains_proof(self):
        import reporting.journal_recovery as recovery
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'history.jsonl'; journal.append_jsonl(p, event('old'))
            interrupt(p, 'rename'); first = inspect_rotation(p)
            save = recovery._save
            def fault(path, value):
                if path == journal._paths(p)[1]: raise OSError('synthetic repeated crash')
                return save(path, value)
            with patch.object(recovery, '_save', side_effect=fault):
                with self.assertRaises(OSError): recover_rotation(p, first['approval_token'])
            second = inspect_rotation(p)
            self.assertNotEqual(first['approval_token'], second['approval_token'])
            recover_rotation(p, second['approval_token'])
            self.assertTrue((p.with_name(p.name+'.recovery')/first['approval_token']/'plan.json').exists())
            self.assertEqual(len(journal.receipts(p)), 1)

    def test_symlinked_completion_proof_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'history.jsonl'; journal.append_jsonl(p, event('old'))
            interrupt(p, 'rename'); plan = inspect_rotation(p)
            outside = Path(tmp)/'elsewhere'; outside.mkdir()
            p.with_name(p.name+'.recovery').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(journal.JournalEvidenceError): recover_rotation(p, plan['approval_token'])
            self.assertEqual(list(outside.iterdir()), [])
