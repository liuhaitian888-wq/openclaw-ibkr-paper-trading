from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from reporting.database_console import collect, render, contained


class DatabaseConsoleTests(unittest.TestCase):
    def test_missing_database_is_not_created_and_html_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = collect(root)
            self.assertEqual(len(result['databases']), 4)
            self.assertTrue(all(x['state'] == 'NOT_CREATED' for x in result['databases']))
            self.assertEqual(list(root.iterdir()), [])
            page = render(result)
            self.assertIn('当前库：未执行完整性检查', page)
            self.assertIn('刷新页面不会重新查询服务器', page)

    def test_wal_rows_are_visible_without_checkpoint_or_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);p = root/'trading_audit.sqlite3'
            with closing(sqlite3.connect(p)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE paper_readback_observations(observed_at TEXT)')
                writer.execute("INSERT INTO paper_readback_observations VALUES('2026-11-06T22:00:00+00:00')")
                writer.commit()
                before = {x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in (p,Path(str(p)+'-wal'))}
                d = collect(root)['databases'][0]
                after = {x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in (p,Path(str(p)+'-wal'))}
                self.assertEqual(before, after)
                self.assertEqual(d['journal_mode'], 'wal')
                self.assertEqual(d['state'], 'READABLE_METADATA')
                self.assertEqual(d['last_business_at'], '2026-11-06T22:00:00+00:00')
                self.assertEqual(d['live_integrity'], 'NOT_CHECKED')
                self.assertGreater(d['wal_bytes'], 0)

    def test_corrupt_and_symlinked_databases_do_not_hide_other_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root/'trading_audit.sqlite3').write_bytes(b'not sqlite')
            (root/'financial_ledger.sqlite3').symlink_to(root/'trading_audit.sqlite3')
            result = collect(root)
            self.assertEqual([r['state'] for r in result['databases'][:2]],
                             ['UNREADABLE_OR_REFUSED']*2)
            self.assertEqual(len(result['databases']), 4)
            with self.assertRaises(ValueError):
                contained(root, '../secrets')

    def test_backup_records_are_not_current_integrity_or_verified_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);b = root/'backups'/'20260101T010000';b.mkdir(parents=True)
            (b/'audit.gz').write_bytes(b'not verified')
            manifest = dict(created_at='20260101T010000.000000Z', items=[
                dict(source='trading_audit.sqlite3',file='audit.gz',status='BACKED_UP',sha256_uncompressed='a'*64),
                dict(source='financial_ledger.sqlite3',file='../../outside',status='BACKED_UP')])
            (b/'backup.json').write_text(json.dumps(manifest))
            d = collect(root, now=datetime(2026,11,7,tzinfo=timezone.utc).timestamp())
            backup = d['databases'][0]['backup']
            self.assertTrue(backup['file_present'])
            self.assertFalse(backup['checksum_verified'])
            self.assertEqual(backup['integrity'], 'NOT_INDEPENDENTLY_VERIFIED')
            self.assertIsNone(d['databases'][1]['backup'])
            self.assertIn('超过48小时', render(d))
            # A manifest value must not become script or HTML markup.
            d['databases'][0]['name'] = '<script>alert(1)</script>'
            page = render(d)
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)

    def test_future_business_time_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with closing(sqlite3.connect(root/'financial_ledger.sqlite3')) as c,c:
                c.execute('CREATE TABLE observations(inserted_at TEXT)')
                c.execute("INSERT INTO observations VALUES('2099-01-01T00:00:00+00:00')")
            self.assertIsNone(collect(root)['databases'][1]['last_business_at'])
