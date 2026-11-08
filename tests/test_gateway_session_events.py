from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.gateway_session_events import collect,SOURCE,phase
from reporting.notification_center import audience,category
from reporting.notification_text import notification_text


class GatewaySessionEventsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=1000
        self.s=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)

    def row(self,key,text,at=1001):return {'__CURSOR':key,'MESSAGE':text,'__REALTIME_TIMESTAMP':str(at*1000000)}
    def collect(self,rows):return collect(self.s,self.root,reader=lambda cursor:rows)
    def baseline(self):
        self.collect([self.row('old','START_RESULT None',900)])
        self.now=1002

    def test_baseline_no_history_replay_and_new_session_queues_private_once(self):
        self.baseline();self.assertIsNone(self.s.claim())
        row=self.row('new','2026-date SOFT_RESTART_COMPLETED_REQUIRES_API_RECONCILIATION')
        with patch('subprocess.run') as run:self.collect([row]);self.collect([row])
        run.assert_not_called()
        item=self.s.claim();self.assertEqual(item['kind'],'AUTH_SESSION_EVENT')
        self.assertEqual(category(item),'auth');self.assertEqual(audience(item,{'audience_mode':'shared_group'}),'owner')
        self.assertIn('等待',item['payload']['reason']);self.assertNotIn('故障批次',notification_text(item,1002))
        self.s.finish(item['id'],'UNKNOWN');self.collect([row]);self.assertIsNone(self.s.claim())
        self.collect([self.row('different','START_RESULT None')])
        self.assertIsNotNone(self.s.claim()) # independent native occurrence, not replay

    def test_new_initialization_needs_new_complete_readback(self):
        self.baseline();self.collect([self.row('init','START_RESULT None')])
        first=self.s.claim();self.s.finish(first['id'],'TELEGRAM_ACCEPTED')
        state=dict(connected=True,identity=True,upstream_connected=True,dirty=False,last_server_reply=1002,
                   ends=['positions','orders','completed_orders','executions'],reconciled_at=999)
        with closing(self.s.connect()) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(state),))
        self.collect([]);self.assertIsNone(self.s.claim())
        state['reconciled_at']=1002
        with closing(self.s.connect()) as c,c:c.execute('UPDATE paper_safety_state SET payload=?',(json.dumps(state),))
        self.collect([]);self.collect([])
        item=self.s.claim();self.assertEqual(item['payload']['phase'],'ACCOUNT_VERIFIED')
        self.assertIn('行情与交易门禁仍独立',item['payload']['reason']);self.assertIsNone(self.s.claim())

    def test_malformed_or_failed_reader_does_not_advance_or_publish(self):
        self.baseline()
        with closing(self.s.connect()) as c:before=c.execute('SELECT payload FROM incident_cursors WHERE source=?',(SOURCE,)).fetchone()
        with self.assertRaises(ValueError):self.collect([self.row('bad','GATEWAY_EXITED',at=99999)])
        with self.assertRaises(RuntimeError):collect(self.s,self.root,reader=lambda _:(_ for _ in ()).throw(RuntimeError('cursor vacuumed')))
        with closing(self.s.connect()) as c:self.assertEqual(c.execute('SELECT payload FROM incident_cursors WHERE source=?',(SOURCE,)).fetchone(),before)
        self.assertIsNone(self.s.claim())

    def test_new_conflict_invalidates_pending_readback_without_asserting_takeover(self):
        self.baseline();self.collect([self.row('init','START_RESULT None'),self.row('conflict','START_RESULT ExistingSessionDetected')])
        with closing(self.s.connect()) as c:state=json.loads(c.execute('SELECT payload FROM incident_cursors WHERE source=?',(SOURCE,)).fetchone()[0])
        self.assertEqual(state['pending'],[])
        self.assertIsNone(phase('Loading credentials private text'))
        self.assertIn('不能证明',phase('Existing session detected')[1])
