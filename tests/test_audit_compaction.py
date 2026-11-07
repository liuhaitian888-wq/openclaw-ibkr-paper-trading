from contextlib import closing
from pathlib import Path
import sqlite3,tempfile,unittest
from reporting.audit_compaction import build

class AuditCompactionTests(unittest.TestCase):
    def test_preserves_rows_rowids_blobs_indices_sequence_and_legacy_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.sqlite3';out=root/'candidate.sqlite3'
            with closing(sqlite3.connect(source)) as c,c:
                c.executescript('CREATE TABLE current(id INTEGER PRIMARY KEY AUTOINCREMENT,data BLOB);CREATE INDEX current_data ON current(data);CREATE TABLE legacy_epoch_old(x);INSERT INTO legacy_epoch_old VALUES(7);')
                c.execute('INSERT INTO current(id,data) VALUES(?,?)',(41,b'\x00proof'));c.execute('UPDATE sqlite_sequence SET seq=99 WHERE name=\'current\'')
            result=build(source,out);self.assertFalse(result['production_activated']);self.assertEqual(result['retained']['current']['rows'],1)
            with closing(sqlite3.connect(out)) as c:
                self.assertEqual(c.execute('SELECT rowid,data FROM current').fetchone(),(41,b'\x00proof'))
                self.assertEqual(c.execute('SELECT seq FROM sqlite_sequence').fetchone()[0],99)
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='legacy_epoch_old'").fetchone())
            with closing(sqlite3.connect(source)) as c:self.assertEqual(c.execute('SELECT x FROM legacy_epoch_old').fetchone()[0],7)
            with self.assertRaises(ValueError):build(source,out)
    def test_cross_namespace_dependency_is_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'s.sqlite3'
            with closing(sqlite3.connect(source)) as c,c:c.executescript('CREATE TABLE legacy_epoch_old(id PRIMARY KEY);CREATE TABLE live(id REFERENCES legacy_epoch_old(id));')
            with self.assertRaises(ValueError):build(source,root/'out.sqlite3')
