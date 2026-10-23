"""Actual WAL backup/restore, plus uncertain SMTP outcome replay protection."""
from contextlib import closing, redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from ops.cloud import backup_state, alert_email


class CloudBackupTests(unittest.TestCase):
    def test_committed_wal_is_preserved_without_creating_missing_financial_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); root=home/'.local/state/openclaw'; root.mkdir(parents=True)
            source=root/'trading_audit.sqlite3'
            with closing(sqlite3.connect(source)) as c:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE evidence (intent TEXT)')
                c.execute("INSERT INTO evidence VALUES ('accepted-unknown')"); c.commit()
                self.assertTrue(Path(str(source)+'-wal').is_file())
                with patch.object(Path,'home',return_value=home), redirect_stdout(io.StringIO()):
                    backup_state.main()
                target=next((root/'backups').iterdir())
                manifest=json.loads((target/'backup.json').read_text())
                self.assertFalse(manifest['cross_database_atomic'])
                item=manifest['items'][0]
                with gzip.open(target/item['file'],'rb') as f: raw=f.read()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256_uncompressed'])
                restored=home/'restore.sqlite3'; restored.write_bytes(raw)
                with closing(sqlite3.connect(restored)) as restored_db:
                    self.assertEqual(restored_db.execute('SELECT intent FROM evidence').fetchone()[0],'accepted-unknown')
                self.assertFalse((root/'financial_ledger.sqlite3').exists())

    def test_smtp_accepted_then_disconnect_is_not_automatically_sent_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); runtime=home/'.local/state/openclaw/runtime'; runtime.mkdir(parents=True)
            config=home/'.config/openclaw/smtp.json'; config.parent.mkdir(parents=True)
            config.write_text(json.dumps(dict(host='relay.invalid',sender='paper@example.invalid',username='fixture',relay_password='fixture'))); config.chmod(0o600)
            (runtime/'EMAIL_ALERTS_ARMED').touch()
            (runtime/'cloud-status.json').write_text(json.dumps(dict(observed_at=datetime.now(timezone.utc).isoformat(),smoke=dict(overall='NOT_READY',checks={}),services={},disk_free_fraction=.9)))
            smtp=Mock(); smtp.__enter__=Mock(return_value=smtp); smtp.__exit__=Mock(return_value=False)
            smtp.send_message.side_effect=ConnectionError('accepted but ACK lost')
            with patch.object(Path,'home',return_value=home), patch.object(alert_email.smtplib,'SMTP',return_value=smtp) as factory, redirect_stdout(io.StringIO()):
                with self.assertRaises(ConnectionError): alert_email.main()
                self.assertEqual(json.loads((runtime/'email-alert-ledger.json').read_text())['status'],'UNKNOWN')
                alert_email.main()
            factory.assert_called_once(); smtp.send_message.assert_called_once()
