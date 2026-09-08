import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from scripts.reconcile_recovered_transition import reconcile, digest


class RecoveryTests(unittest.TestCase):
    def test_exact_proof_and_repeat_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); recovered = root/'recovered.db'; healthy = root/'healthy.db'; output = root/'proof.db'
            event = {'transition_id': 't1', 'symbol': 'MU', 'reason_code': 'MISSING_BID'}
            with closing(sqlite3.connect(recovered)) as c, c:
                c.execute('CREATE TABLE canonical_pool_transition_events (transition_id TEXT,symbol TEXT,reason_code TEXT,payload_json TEXT)')
                c.execute('INSERT INTO canonical_pool_transition_events VALUES (?,?,?,?)', ('t1','MU','MISSING_BID',json.dumps(event)))
            with closing(sqlite3.connect(healthy)) as c, c:
                c.execute('CREATE TABLE canonical_pool_state (symbol TEXT,payload_json TEXT)')
                c.execute('INSERT INTO canonical_pool_state VALUES (?,?)', ('MU',json.dumps({'transition_history':[event]})))
            before = [digest(recovered), digest(healthy)]
            self.assertEqual(reconcile(recovered,healthy,'t1',output)['inserted'],1)
            result_hash = digest(output)
            self.assertEqual(reconcile(recovered,healthy,'t1',output)['inserted'],0)
            self.assertEqual(result_hash,digest(output))
            self.assertEqual(before,[digest(recovered),digest(healthy)])
            with closing(sqlite3.connect(healthy)) as c, c:
                event['reason_code']='OTHER'
                c.execute('UPDATE canonical_pool_state SET payload_json=?',(json.dumps({'transition_history':[event]}),))
            with self.assertRaises(ValueError):reconcile(recovered,healthy,'t1',root/'unproved.db')
            self.assertFalse((root/'unproved.db').exists())
            self.assertEqual(result_hash,digest(output))
