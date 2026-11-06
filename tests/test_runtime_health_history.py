from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from reporting.runtime_history import record,monitor_states
from ops.cloud.inspect_health_window import inspect

class RuntimeHistoryTests(unittest.TestCase):
 def test_transitions_epoch_same_state_and_sample_gaps(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'runtime').mkdir()
   with closing(sqlite3.connect(root/'runtime/recovery.sqlite3')) as c,c:
    for t,epoch,state in [(100,'a','CONNECTED'),(101,'a','CONNECTED'),(102,'a','DISCONNECTED'),(103,'a','CONNECTED'),(300,'b','CONNECTED')]:
     record(c,'paper-safety',epoch,t,{'api':state},{})
    self.assertEqual(c.execute('select count(*) from runtime_health_events').fetchone()[0],4)
    self.assertEqual(c.execute('select previous from runtime_health_events order by id desc limit 1').fetchone()[0],'UNKNOWN')
   before=(root/'runtime/recovery.sqlite3').read_bytes()
   d=inspect(root,datetime.fromtimestamp(400,timezone.utc),hours=400/3600)
   self.assertTrue(d['gaps']);self.assertEqual(len(d['events']),4)
   self.assertEqual(before,(root/'runtime/recovery.sqlite3').read_bytes())
 def test_fresh_history_does_not_prove_realtime_bars_or_quotes(self):
  state=dict(connected=True,identity=True,upstream_connected=True,last_server_reply=300,bars={},history_evidence={'PFE':dict(complete=True,completed_ends=[240,300],received_at=300)})
  s,e=monitor_states(state,{'PFE':{'status':'UNKNOWN'}},['PFE'],300,2)
  self.assertEqual(s['market.history.PFE'],'VERIFIED_FRESH');self.assertEqual(s['market.bars.PFE'],'UNVERIFIED')
  s,e=monitor_states(state,{},['PFE'],400,2);self.assertEqual(s['market.history.PFE'],'UNVERIFIED')
 def test_naive_end_rejected(self):
  with self.assertRaises(ValueError):inspect('/missing',datetime(2026,1,1))

 def test_heartbeat_ack_and_unknown_are_persisted_without_endpoint(self):
  from ops.cloud.healthchecks_sender import heartbeat_attempt
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   self.assertTrue(heartbeat_attempt(root,'host_url',True,lambda:200))
   def lost_response():raise TimeoutError('private endpoint must not be recorded')
   self.assertFalse(heartbeat_attempt(root,'host_url',True,lost_response))
   with closing(sqlite3.connect(root/'recovery.sqlite3')) as c:
    rows=c.execute('SELECT outcome,ack,http_status FROM heartbeat_delivery ORDER BY id').fetchall()
    self.assertEqual(rows[0][0],'HTTP_ACCEPTED');self.assertIsNotNone(rows[0][1])
    self.assertEqual(rows[1],('UNKNOWN',None,None))

 def test_api_heartbeat_requires_fresh_owned_identity_and_readback(self):
  from ops.cloud.healthchecks_sender import api_evidence
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   self.assertFalse(api_evidence(root,1000,'DUQ503649'))
   self.assertFalse((root/'recovery.sqlite3').exists())
   with closing(sqlite3.connect(root/'recovery.sqlite3')) as c,c:
    c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)')
    state=dict(identity=True,connected=True,upstream_connected=True,last_server_reply=995,reconciled_at=980)
    c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(state),))
   self.assertTrue(api_evidence(root,1000,'DUQ503649'))
   self.assertFalse(api_evidence(root,1100,'DUQ503649'))
   self.assertFalse(api_evidence(root,1000,'WRONG'))
