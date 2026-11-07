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
