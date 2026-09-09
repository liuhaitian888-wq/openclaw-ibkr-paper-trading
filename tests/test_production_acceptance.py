import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import closing
from reporting.health import resolve_modules
from reporting.recovery import RecoveryCoordinator,wire_live_adapters
from trading.production_paths import maintenance_active

class ProductionAcceptanceTests(unittest.TestCase):
 def test_evidence_directory_is_not_maintenance_flag(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'maintenance').mkdir()
   self.assertFalse(maintenance_active(root))
   (root/'runtime').mkdir();(root/'runtime/MAINTENANCE').touch()
   self.assertTrue(maintenance_active(root))
   self.assertTrue((root/'maintenance').is_dir())
 def test_legacy_file_marker_still_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'MAINTENANCE').touch()
   self.assertTrue(maintenance_active(root))
 def test_old_diagnostics_cannot_stay_healthy(self):
  now=datetime.now(timezone.utc)
  modules=resolve_modules({'DIAGNOSTICS':{'state':'HEALTHY','freshness':'FRESH','observed_at':(now-timedelta(hours=1)).isoformat()}},now=now)
  self.assertEqual(modules['DIAGNOSTICS']['state'],'DEGRADED')
 def test_legacy_pending_submitted_failed_and_unknown_are_held(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'production.json').write_text('{}')
   co=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
   with closing(sqlite3.connect(root/'trading_audit.sqlite3')) as c,c:
    c.executescript('CREATE TABLE order_requests(idempotency_key TEXT,status TEXT); CREATE TABLE reconciliation_runs(completed_at TEXT,status TEXT);')
    c.execute('INSERT INTO reconciliation_runs VALUES (?,?)',(datetime.now(timezone.utc).isoformat(),'OK'))
    statuses=['PAPER_PENDING_CONFIRMATION','PAPER_LIMIT_PENDING_CONFIRMATION','LIMIT_STAGE_PENDING_CONFIRMATION','PAPER_LIMIT_SUBMITTED','FAILED','UNKNOWN','STARTED']
    c.executemany('INSERT INTO order_requests VALUES (?,?)',[(str(i),s) for i,s in enumerate(statuses)])
   adapter=wire_live_adapters(co,root,root)['ORDER_SUBMISSION']
   self.assertFalse(adapter('connect'))
   self.assertEqual(len(adapter.observation['evidence']['pending']),len(statuses))
