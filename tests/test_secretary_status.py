from contextlib import closing
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from reporting.secretary_status import display
from reporting.secretary_controls import menu_commands

class StatusTests(unittest.TestCase):
    def test_missing_evidence_never_creates_database(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.assertIn('UNKNOWN',display(root,'api'))
            self.assertFalse((root/'runtime').exists())

    def test_old_healthy_evidence_is_not_current(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'runtime').mkdir()
            with closing(sqlite3.connect(root/'runtime/recovery.sqlite3')) as c,c:
                c.execute('CREATE TABLE module_observations(name TEXT,payload TEXT)')
                c.execute('INSERT INTO module_observations VALUES (?,?)',('SECRETARY_MODEL',json.dumps(dict(state='HEALTHY',freshness='FRESH',observed_at='2020-01-01T00:00:00+00:00'))))
            result=display(root,'api',now=datetime(2026,11,10,tzinfo=timezone.utc))
            self.assertIn('SECRETARY_MODEL：未证实当前正常',result)

    def test_menu_contains_deterministic_status_entries(self):
        commands=dict(menu_commands())
        self.assertTrue({'api','cloud','market'} <= commands.keys())
