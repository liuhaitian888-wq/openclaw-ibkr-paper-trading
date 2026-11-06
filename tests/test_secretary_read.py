from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from reporting.secretary_read import query,tool

class SecretaryReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        with closing(sqlite3.connect(self.root/'agent_secretary.sqlite3')) as c,c:
            c.execute('CREATE TABLE evidence(id INTEGER, payload TEXT)')
            c.executemany('INSERT INTO evidence VALUES(?,?)',[(i,'{"password":"fixture-value"}') for i in range(120)])
    def test_all_registered_database_ids_are_available_and_missing_never_created(self):
        for name in ('trading_audit.sqlite3','financial_ledger.sqlite3','runtime/recovery.sqlite3'):
            self.assertEqual(query(self.root,name,'SELECT 1')['state'],'NOT_CREATED')
            self.assertFalse((self.root/name).exists())
        self.assertEqual(len(tool(self.root,{'name':'schema','database':'agent_secretary.sqlite3'})['rows']),1)
    def test_rows_budget_and_secret_redaction(self):
        data=query(self.root,'agent_secretary.sqlite3','SELECT * FROM evidence')
        self.assertEqual(len(data['rows']),100);self.assertTrue(data['truncated'])
        self.assertNotIn('fixture-value',str(data))
    def test_writes_attach_pragmas_extensions_and_multiple_statements_refused(self):
        for sql in ('DELETE FROM evidence','UPDATE evidence SET id=1','PRAGMA journal_mode=WAL',
                    "ATTACH DATABASE ':memory:' AS extra","SELECT load_extension('bad')",'SELECT 1; DELETE FROM evidence',
                    'SELECT randomblob(10000000)'):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.Error):query(self.root,'agent_secretary.sqlite3',sql)
        self.assertEqual(query(self.root,'agent_secretary.sqlite3','SELECT count(*) AS n FROM evidence')['rows'][0]['n'],120)
    def test_recursive_query_deadline(self):
        with self.assertRaises(sqlite3.OperationalError):
            query(self.root,'agent_secretary.sqlite3','WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n',budget=.005)
    def test_paths_symlinks_and_arbitrary_tools_refused(self):
        with self.assertRaises(ValueError):query(self.root,'../agent_secretary.sqlite3','SELECT 1')
        (self.root/'financial_ledger.sqlite3').symlink_to(self.root/'agent_secretary.sqlite3')
        with self.assertRaises(ValueError):query(self.root,'financial_ledger.sqlite3','SELECT 1')
        with self.assertRaises(PermissionError):tool(self.root,{'name':'shell','command':'echo bad'})
    def test_hypothesis_test_uses_actual_database_result(self):
        request={'name':'hypothesis_test','database':'agent_secretary.sqlite3','sql':'SELECT count(*) FROM evidence','comparison':'gt','expected':200}
        self.assertEqual(tool(self.root,request)['result'],'FALSIFIED')
        request['expected']=100
        self.assertEqual(tool(self.root,request)['result'],'SUPPORTED')
        request['sql']='SELECT id FROM evidence'
        self.assertEqual(tool(self.root,request)['result'],'INCONCLUSIVE')
