import tempfile
import unittest
from pathlib import Path
from contextlib import closing
import sqlite3
from trading.pool_state import PoolStateManager
from scripts.build_reconciled_schema import build
from scripts.reconcile_recovered_transition import digest
import ast

class FinalSchemaTests(unittest.TestCase):
 def test_duplicate_loader_refuses_without_partial_state(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.sqlite3';m=PoolStateManager(db_path=p);m.upsert_master(symbol='AAPL');m.save()
   with closing(sqlite3.connect(p)) as c,c:c.execute('INSERT INTO canonical_pool_state SELECT * FROM canonical_pool_state')
   old=m.get('AAPL')
   with self.assertRaisesRegex(ValueError,'Ambiguous canonical'):m.load()
   self.assertEqual(m.get('AAPL'),old)
 def test_typed_schema_preserves_original_and_repeat(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source';out=Path(d)/'out';root=Path(__file__).resolve().parents[1]
   with closing(sqlite3.connect(p)) as c,c:
    for n in ast.walk(ast.parse((root/'trading/audit.py').read_text())):
     if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.strip().startswith('CREATE TABLE'):c.execute(n.value)
    c.execute('CREATE TABLE profit_sell_events (spread_ok BLOB)');c.execute("INSERT INTO profit_sell_events VALUES ('0')")
   before=digest(p);self.assertEqual(build(p,out,root)['inserted'],1);self.assertEqual(digest(p),before)
   with closing(sqlite3.connect(out)) as c:
    self.assertEqual(c.execute('select spread_ok,typeof(spread_ok) from profit_sell_events').fetchone(),(0,'integer'))
    self.assertEqual(c.execute('select spread_ok from schema_original_profit_sell_events').fetchone(),('0',))
   h=digest(out);self.assertEqual(build(p,out,root)['inserted'],0);self.assertEqual(h,digest(out))
