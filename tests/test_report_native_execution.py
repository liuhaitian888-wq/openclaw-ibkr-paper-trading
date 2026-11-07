from contextlib import closing
from datetime import datetime,timezone
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts.report_aggregation import stamp
from trading.audit import AuditLog

class NativeExecutionReportTests(unittest.TestCase):
    def test_broker_eastern_alias_uses_canonical_iana_zone_on_minimal_linux(self):
        real=ZoneInfo
        def zone(name):
            if name=='US/Eastern':raise KeyError('legacy timezone aliases not installed')
            return real(name)
        with patch('scripts.report_aggregation.ZoneInfo',side_effect=zone):
            self.assertEqual(stamp('20261106 11:32:46 US/Eastern'),datetime(2026,11,6,16,32,46,tzinfo=timezone.utc))
            self.assertIsNone(stamp('20261106 11:32:46'))
    def test_verified_contract_metadata_survives_older_callbacks_but_conflicts_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=AuditLog(Path(tmp)/'a.sqlite3')
            execution={'exec_id':'native.01','account':'DU123','order_id':1,'symbol':'NVDA','side':'BOT','shares':1,'price':188.72,'time':'20261106 11:32:46 US/Eastern'}
            with closing(a._connect()) as c,c:
                a._upsert_execution(c,execution,'2026-11-06T16:33:05Z')
                a._upsert_execution(c,{**execution,'currency':'USD','sec_type':'STK','con_id':4815747},'2026-11-07T01:00:00Z')
                a._upsert_execution(c,execution,'2026-11-07T01:00:01Z')
                stored=json.loads(c.execute('SELECT raw_json FROM executions').fetchone()[0]);self.assertEqual(stored['currency'],'USD')
                with self.assertRaises(ValueError):a._upsert_execution(c,{**execution,'currency':'EUR'},'2026-11-07T01:00:02Z')
    def test_finite_native_journal_counts_are_not_lost_or_double_counted(self):
        from scripts.report_aggregation import aggregate_activity
        with closing(sqlite3.connect(':memory:')) as c:
            c.row_factory=sqlite3.Row;c.execute('CREATE TABLE paper_acceptance_attempts(status TEXT,payload TEXT)')
            for n,status,native in [(1,'CANCELLED','Cancelled'),(2,'FILLED','Filled'),(3,'FILLED','Filled'),(4,'UNKNOWN','Submitted')]:
                payload={'account':'DU123','grants_strategy_permission':False,'orders_sent':1,'perm_id':n,'order_id':n,'native_status':native,'submission_started_at':'2026-11-06T16:00:00Z','completed_at':'2026-11-06T16:01:00Z'}
                c.execute('INSERT INTO paper_acceptance_attempts VALUES(?,?)',(status,json.dumps(payload)))
            start=datetime(2026,11,6,tzinfo=timezone.utc);end=datetime(2026,11,7,tzinfo=timezone.utc)
            result=aggregate_activity(c,start,end,'DU123',{})
            self.assertEqual(result['orders_submitted']['value'],3);self.assertEqual(result['filled_orders']['value'],2);self.assertEqual(result['cancelled_orders']['value'],1)
            self.assertFalse(result['coverage_complete']);self.assertIsNone(result['commissions']['value'])
