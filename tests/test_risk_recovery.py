from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.risk_recovery import ingest_recoveries


class RiskRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.store=IncidentStore(Path(temporary.name)/'recovery.db',clock=lambda:1000)

    def batch(self,symbols):
        result=[]
        for symbol in symbols:
            key='paper-safety:protection:'+symbol
            self.store.ingest('open:'+symbol,key,dict(severity='RED',symbol=symbol))
            result.append(('close:'+symbol,key,dict(severity='GREEN',symbol=symbol,protection_status='PROTECTED')))
        return result

    def rows(self):
        with closing(self.store.connect()) as c:
            return c.execute('SELECT id,kind,status,payload FROM notification_outbox ORDER BY id').fetchall()

    def test_seven_recoveries_one_digest_and_individual_evidence(self):
        batch=self.batch(['AAPL','MSFT','META','T','PFE','NIO','NVDA'])
        batch[-1][2]['protection_status']='NO_EXPOSURE'
        self.store.ingest('still-open','paper-safety:protection:XYZ',dict(severity='RED'))
        ident=ingest_recoveries(self.store,batch)
        recoveries=[r for r in self.rows() if r[1]=='RECOVERY']
        self.assertEqual(len(recoveries),8)
        self.assertEqual(sum(r[2]=='PENDING' for r in recoveries),1)
        self.assertEqual(sum(r[2]=='SUPPRESSED' for r in recoveries),7)
        payload=json.loads(next(r[3] for r in recoveries if r[0]==ident))
        self.assertEqual(payload['recovered_count'],7)
        self.assertEqual(payload['unresolved_count'],1)
        self.assertIn('仍有问题：XYZ',payload['reason'])
        self.assertIn('无持仓、无挂单，旧故障关闭：NVDA',payload['reason'])
        self.assertFalse(payload['grants_trading_permission'])
        before=self.rows();self.assertIsNone(ingest_recoveries(self.store,batch))
        self.assertEqual(before,self.rows())

    def test_rollback_preserves_open_incidents_and_no_partial_recovery(self):
        batch=self.batch(['A','B']);original=self.store._ingest
        def fail(c,event,*args):
            if event=='close:B':raise RuntimeError('simulated storage failure')
            return original(c,event,*args)
        with patch.object(self.store,'_ingest',side_effect=fail):
            with self.assertRaises(RuntimeError):ingest_recoveries(self.store,batch)
        self.assertFalse(any(r[1]=='RECOVERY' for r in self.rows()))
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM incidents WHERE state='OPEN'").fetchone()[0],2)
        self.assertIsNotNone(ingest_recoveries(self.store,batch))

    def test_uncertain_original_alert_is_retained_and_never_replayed(self):
        batch=self.batch(['A']);item=self.store.claim()
        self.store.finish(item['id'],'UNKNOWN')
        ingest_recoveries(self.store,batch)
        self.assertEqual(self.rows()[0][2],'UNKNOWN')
        self.assertEqual(self.rows()[1][2],'SUPPRESSED')
        self.assertEqual(self.rows()[2][2],'PENDING')
        self.assertIsNone(self.store.claim())
        self.assertIsNone(ingest_recoveries(self.store,batch))

    def test_healthy_observation_without_open_incident_sends_nothing(self):
        self.assertIsNone(ingest_recoveries(self.store,[('healthy','paper-safety:protection:A',dict(symbol='A',protection_status='PROTECTED'))]))
        self.assertEqual(self.rows(),[])

    def test_monitor_groups_complete_readback_and_does_not_repeat(self):
        from trading.paper_safety_monitor import PaperSafetyMonitor,ACCOUNT
        monitor=PaperSafetyMonitor(self.store.path.parent/'audit.db',self.store.path,
            symbols=['AAA','BBB'],required_bars=2,clock=lambda:1000)
        monitor.begin([ACCOUNT])
        for ident,symbol in enumerate(['AAA','BBB'],1):
            monitor.position(symbol,2,con_id=ident,currency='USD',sec_type='STK')
        for name in ('orders','completed_orders','executions','positions'):monitor.end(name)
        monitor.start_reconciliation()
        for ident,symbol in enumerate(['AAA','BBB'],1):
            monitor.position(symbol,2,con_id=ident,currency='USD',sec_type='STK')
            monitor.order(dict(order_id=ident,perm_id=ident,account=ACCOUNT,symbol=symbol,
                side='SELL',order_type='STP',status='Submitted',quantity=2,remaining=2,
                transmit=True,parent_id=0,con_id=ident,currency='USD',sec_type='STK'))
        for name in ('orders','completed_orders','executions','positions'):monitor.end(name)
        with closing(self.store.connect()) as c:
            rows=c.execute("SELECT payload,status FROM notification_outbox WHERE incident_key LIKE 'paper-safety:protection-recovery-batch:%'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(json.loads(rows[0][0])['recovered_count'],2)
        self.assertEqual(rows[0][1],'PENDING')
        before=self.rows();monitor._publish();self.assertEqual(before,self.rows())
