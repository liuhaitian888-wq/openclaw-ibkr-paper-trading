from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from ops.cloud.inspect_runtime_timeline import inspect,markdown

class TimelineTests(unittest.TestCase):
 def test_missing_history_is_a_gap_and_never_creates_database(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);d=inspect(r,'2026-11-06')
   self.assertTrue(d['warnings']);self.assertFalse((r/'runtime/recovery.sqlite3').exists())
 def test_local_day_receipts_unknown_and_condition_aggregation(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Path(tmp);(r/'runtime').mkdir();(r/'PAUSED').touch();(r/'production.json').write_text('{"ready":false}')
   from reporting.incidents import IncidentStore
   s=IncidentStore(r/'runtime/recovery.sqlite3');t=datetime.fromisoformat('2026-11-05T23:10:00+00:00').timestamp()
   with closing(s.connect()) as c,c:
    for i,status in ((1,'TELEGRAM_ACCEPTED'),(2,'UNKNOWN')):
     c.execute('INSERT INTO notification_outbox VALUES (?,?,?,?,?,?)',(i,'connection:'+str(i),1,'ALERT',json.dumps(dict(queued_at=t,reason='API_CONNECTION_CLOSED')),status))
    c.execute('INSERT INTO notification_receipts VALUES (?,?)',(1,json.dumps(dict(transport='telegram',message_ids=[9],server_dates=['2026-11-05T23:10:02Z']))))
    c.execute('INSERT INTO notification_delivery VALUES (?,?,?,?,?)',(1,t,t+2,'TELEGRAM_ACCEPTED',None))
    c.execute('CREATE TABLE paper_callback_events(payload TEXT,kind TEXT,observed REAL)')
    c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)')
    c.execute('CREATE TABLE paper_health_samples(observed REAL,payload TEXT)')
    for tick in (t,t+1):c.execute('INSERT INTO paper_callback_events VALUES (?,?,?)',(json.dumps(dict(scope='GLOBAL_NEW_ORDERS_PAUSED',action='PAUSE',reason='OPERATOR_PAUSED')),'pause_transition',tick))
   before=(r/'runtime/recovery.sqlite3').read_bytes();d=inspect(r,'2026-11-06')
   self.assertFalse(d['warnings']);self.assertEqual(len(d['notices']),2)
   self.assertTrue(d['notices'][0]['queued_at'].startswith('2026-11-06T00:10'))
   self.assertEqual(d['notices'][0]['message_ids'],[9]);self.assertIsNone(d['notices'][1]['ack_at'])
   self.assertEqual(d['pause_condition_event_count'],2);self.assertEqual(len(d['pause_conditions']),1)
   self.assertIsNone(d['global_gate']['pause_started_at']);self.assertIn('不能当作停机次数',markdown(d))
   self.assertEqual(before,(r/'runtime/recovery.sqlite3').read_bytes())
