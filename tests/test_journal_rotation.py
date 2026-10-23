from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.incident_sources import IncidentCollector, EvidenceChanged
from reporting.journal_rotation import append_jsonl, rotate_journal, receipts, JournalEvidenceError


def event(key):
    return dict(timestamp='2026-10-23T15:00:00+00:00',local_plan_id=key,symbol='AAPL')


class RotationTests(unittest.TestCase):
    def setup_source(self, tmp):
        path=Path(tmp)/'history.jsonl'
        store=IncidentStore(Path(tmp)/'shadow.sqlite3')
        return path,store,IncidentCollector(store)

    def count(self, store):
        with closing(store.connect()) as c:
            return c.execute('SELECT COUNT(*) FROM incident_events').fetchone()[0]

    def test_unread_tail_then_new_segment_with_batch_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('historical'))
            collector.rejections(path)
            append_jsonl(path,event('old-unread'))
            receipt=rotate_journal(path)
            append_jsonl(path,event('new'))
            self.assertEqual(collector.rejections(path,limit=1),1)
            self.assertEqual(IncidentCollector(IncidentStore(store.path)).rejections(path,limit=1),1)
            self.assertEqual(collector.rejections(path),0)
            self.assertEqual(self.count(store),2)
            self.assertTrue((path.with_name(path.name+'.segments')/receipt['archive']).exists())
            self.assertEqual(len(receipts(path)),1)

    def test_missing_baseline_drains_multiple_receipts_and_identical_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            collector.rejections(path)
            for _ in range(3):
                append_jsonl(path,event('same-order'))
                rotate_journal(path)
            append_jsonl(path,event('same-order'))
            self.assertEqual(collector.rejections(path),4)
            self.assertEqual(collector.rejections(path),0)
            self.assertEqual(self.count(store),4)  # Content equality is not occurrence identity.
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0],1)

    def test_first_existing_baseline_never_replays_old_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('old1')); rotate_journal(path)
            append_jsonl(path,event('old2'))
            self.assertEqual(collector.rejections(path),0)
            rotate_journal(path); append_jsonl(path,event('current'))
            self.assertEqual(collector.rejections(path),1)
            self.assertEqual(self.count(store),1)

    def test_tampered_missing_archive_and_broken_chain_do_not_advance_cursor(self):
        for failure in ('tamper','missing','chain'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                path,store,collector=self.setup_source(tmp)
                collector.rejections(path)
                append_jsonl(path,event('unread'))
                receipt=rotate_journal(path)
                append_jsonl(path,event('current'))
                archive=path.with_name(path.name+'.segments')/receipt['archive']
                if failure=='tamper':
                    archive.write_bytes(archive.read_bytes().replace(b'AAPL',b'MSFT'))
                elif failure=='missing':
                    archive.rename(archive.with_suffix('.preserved'))
                else:
                    manifest=path.with_name(path.name+'.rotation.json')
                    value=json.loads(manifest.read_text());value['segments'][0]['old_inode']=[0,123]
                    manifest.write_text(json.dumps(value))
                with self.assertRaises(EvidenceChanged):
                    collector.rejections(path)
                self.assertEqual(self.count(store),0)

    def test_pending_rotation_preserves_source_and_blocks_writer_and_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('old'))
            collector.rejections(path)
            before=path.read_bytes()
            with patch.object(Path,'rename',side_effect=OSError('interrupted rename')):
                with self.assertRaises(OSError):rotate_journal(path)
            self.assertEqual(path.read_bytes(),before)
            self.assertTrue(path.with_name(path.name+'.rotation.pending').exists())
            with self.assertRaises(JournalEvidenceError):append_jsonl(path,event('blocked'))
            with self.assertRaises(EvidenceChanged):collector.rejections(path)
            self.assertEqual(self.count(store),0)

    def test_partial_tail_is_not_cleared_rotated_or_silently_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            collector.rejections(path)
            path.write_text('{"partial":')
            before=path.read_bytes()
            with self.assertRaises(JournalEvidenceError):rotate_journal(path)
            with self.assertRaises(JournalEvidenceError):append_jsonl(path,event('blocked'))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(collector.rejections(path),0)

    def test_concurrent_producers_and_automatic_rotation_have_no_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            collector.rejections(path)
            def write_batch(n):
                for i in range(20):append_jsonl(path,event(f'{n}-{i}'),max_bytes=400)
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(write_batch,range(4)))
            for _ in range(4):collector.rejections(path)
            self.assertEqual(self.count(store),80)
            self.assertGreater(len(receipts(path)),1)
            self.assertEqual(collector.rejections(path),0)

    def test_copytruncate_without_receipt_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('old'));collector.rejections(path)
            path.write_text('')
            with self.assertRaises(EvidenceChanged):collector.rejections(path)
            self.assertEqual(self.count(store),0)

    def test_read_only_missing_source_does_not_create_directories_or_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            source=Path(tmp)/'missing'/'history.jsonl'
            self.assertEqual(collector.rejections(source),0)
            self.assertFalse(source.parent.exists())

    def test_isolated_shadow_acceptance_never_uses_real_transport(self):
        from ops.cloud.shadow_incident_acceptance import run_shadow
        with tempfile.TemporaryDirectory() as tmp:
            result=run_shadow(Path(tmp)/'isolated-shadow')
            self.assertTrue(result['simulation_only'])
            self.assertEqual(result['attempted_network_connections'],0)
            self.assertTrue(all(value=='PASS' for value in result['outcomes'].values()))

    def test_owned_writer_detects_identical_byte_copytruncate_regrowth(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('old'));collector.rejections(path)
            raw=path.read_bytes(); old=path.stat()
            path.write_bytes(raw)
            os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns+1000000))
            with self.assertRaises(EvidenceChanged):collector.rejections(path)
            with self.assertRaises(JournalEvidenceError):append_jsonl(path,event('blocked'))
            self.assertEqual(self.count(store),0)

    def test_crash_between_append_and_writer_commit_preserves_bytes_and_watermark(self):
        import reporting.journal_rotation as journal
        with tempfile.TemporaryDirectory() as tmp:
            path,store,collector=self.setup_source(tmp)
            append_jsonl(path,event('baseline'));collector.rejections(path)
            before=path.read_bytes()
            with patch.object(journal,'_save',side_effect=OSError('writer state commit interrupted')):
                with self.assertRaises(OSError):append_jsonl(path,event('retained-uncommitted'))
            self.assertGreater(path.stat().st_size,len(before))
            self.assertTrue(path.read_bytes().startswith(before))
            with self.assertRaises(EvidenceChanged):collector.rejections(path)
            self.assertEqual(self.count(store),0)
