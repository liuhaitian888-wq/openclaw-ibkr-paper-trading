from pathlib import Path
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive


class SecretaryArchiveTests(unittest.TestCase):
    def test_provenance_survives_restart_and_repeated_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'agent_secretary.sqlite3'
            a = SecretaryArchive(path)
            kwargs = dict(origin='USER', kind='MESSAGE', payload={'text': 'Research PFE'})
            self.assertTrue(a.append('tg:10', 'der', **kwargs))
            a = SecretaryArchive(path)
            self.assertFalse(a.append('tg:10', 'der', **kwargs))
            # Identical text at another occurrence is another user instruction.
            self.assertTrue(a.append('tg:11', 'der', **kwargs))
            a.append('analysis:10', 'der', origin='MODEL', kind='ANALYSIS', parent='tg:10',
                     payload={'model': 'fixture-model', 'rationale': 'Public concise explanation',
                              'fee_assumptions': {'currency': 'USD', 'schedule': 'UNVERIFIED'},
                              'backtest_result': None})
            history = a.history('der')
            self.assertEqual([r['origin'] for r in history], ['USER', 'USER', 'MODEL'])
            self.assertEqual(history[-1]['parent'], 'tg:10')
            with self.assertRaises(ValueError):
                a.append('tg:10', 'der', origin='MODEL', kind='MESSAGE', payload={})
            with self.assertRaises(ValueError):
                a.append('bad-parent', 'other', origin='MODEL', kind='ANALYSIS', payload={}, parent='tg:10')

    def test_uncertain_paid_operation_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.sqlite3'
            a = SecretaryArchive(path)
            a.append('user:1', 'der', origin='USER', kind='MESSAGE', payload={})
            self.assertTrue(a.reserve_run('run:1', instruction='user:1', model='fixture-model'))
            a = SecretaryArchive(path)
            self.assertFalse(a.reserve_run('run:1', instruction='user:1', model='fixture-model'))
            a.finish_run('run:1', state='UNKNOWN')
            self.assertFalse(a.reserve_run('run:1', instruction='user:1', model='fixture-model'))
            with self.assertRaises(ValueError):
                a.finish_run('run:1', state='FAILED')
            with self.assertRaises(ValueError):
                a.reserve_run('run:1', instruction='user:1', model='different-model')

    def test_success_requires_attributed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = SecretaryArchive(Path(tmp)/'a.sqlite3')
            a.append('u', 'der', origin='USER', kind='MESSAGE', payload={})
            a.reserve_run('r', instruction='u', model='fixture-model')
            with self.assertRaises(ValueError):
                a.finish_run('r', state='SUCCEEDED', result_event='missing')
            a.append('result', 'der', origin='TOOL', kind='BACKTEST', parent='u', payload={'return': '0.01'})
            self.assertTrue(a.finish_run('r', state='SUCCEEDED', result_event='result'))
            self.assertFalse(a.finish_run('r', state='SUCCEEDED', result_event='result'))
            with self.assertRaises(ValueError):
                a.history('der', limit=0)
