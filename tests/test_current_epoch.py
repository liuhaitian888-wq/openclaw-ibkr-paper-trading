import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.build_reconciled_schema import stage_current_epoch, digest
from trading.audit import AuditLog


class CurrentEpochTests(unittest.TestCase):
    def test_history_preserved_without_executable_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/'source.db', Path(tmp)/'candidate.db'
            AuditLog(source)
            with closing(sqlite3.connect(source)) as c, c:
                c.execute("INSERT INTO order_requests VALUES ('old','then','PAPER','UNKNOWN','{}','keep')")
                c.execute('CREATE TABLE canonical_pool_state(symbol TEXT)')
                c.execute("INSERT INTO canonical_pool_state VALUES ('PFE')")
            before = digest(source)
            proof = stage_current_epoch(source, target, account='DUQ503649')
            self.assertEqual(digest(source), before)
            self.assertFalse(proof['historical_replay_allowed'])
            self.assertFalse(proof['grants_trading_permission'])
            with closing(sqlite3.connect(target)) as c:
                self.assertEqual(c.execute('SELECT idempotency_key,status,details FROM legacy_epoch_order_requests').fetchall(), [('old','UNKNOWN','keep')])
                self.assertEqual(c.execute('SELECT symbol FROM legacy_epoch_canonical_pool_state').fetchall(), [('PFE',)])
                self.assertEqual(c.execute('SELECT count(*) FROM order_requests').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT count(*) FROM canonical_pool_state').fetchone()[0], 0)
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(c.execute("SELECT tbl_name FROM sqlite_master WHERE name='idx_order_events_key_time'").fetchone()[0], 'order_events')
            with self.assertRaises(ValueError):
                stage_current_epoch(source, target, account='DUQ503649')

    def test_account_source_and_sidecar_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/'source.db', Path(tmp)/'candidate.db'
            AuditLog(source)
            for account in ('U1234', 'DU1234', ''):
                with self.assertRaises(ValueError):
                    stage_current_epoch(source, target, account=account)
            Path(str(source)+'-wal').write_bytes(b'unreconciled')
            with self.assertRaisesRegex(ValueError, 'WAL'):
                stage_current_epoch(source, target, account='DUQ503649')
            self.assertFalse(target.exists())
            Path(str(source)+'-wal').unlink()
            target.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                stage_current_epoch(source, target, account='DUQ503649')

    def test_unreviewed_views_rejected_without_creating_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp)/'source.db', Path(tmp)/'candidate.db'
            with closing(sqlite3.connect(source)) as c, c:
                c.execute('CREATE TABLE data(value TEXT)')
                c.execute('CREATE VIEW current_data AS SELECT * FROM data')
            with self.assertRaisesRegex(ValueError, 'Views/triggers'):
                stage_current_epoch(source, target, account='DUQ503649')
            self.assertFalse(target.exists())
