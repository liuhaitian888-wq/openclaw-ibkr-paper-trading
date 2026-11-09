from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from trading.audit import AuditLog
from trading.daily_turnover import execution_instant, native_turnover


class NativeTurnoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.audit=AuditLog(Path(self.temp.name)/'audit.sqlite3')

    def add(self,identity,**fields):
        fact=dict(exec_id=identity,order_id=1,perm_id=1,account='DUQ503649',symbol='BAC',con_id=123,sec_type='STK',currency='USD',side='BOT',shares=2,price=40,time='20261109 09:31:00 US/Eastern')
        fact.update(fields)
        with closing(self.audit._connect()) as c,c:
            self.audit._upsert_execution(c,fact,'2026-11-09T14:32:00+00:00')

    def project(self,day='2026-11-09',zone='America/New_York'):
        with closing(self.audit._connect()) as c:return native_turnover(c,day,zone)

    def test_native_buys_sells_external_fills_and_duplicate_receipts(self):
        self.add('buy');self.add('buy');self.add('protective-exit',side='SLD',shares=1,price=39,order_ref='external')
        p=self.project();self.assertEqual(p['gross_notional'],'119')
        self.assertEqual(p['buy_notional'],'80');self.assertEqual(p['sell_notional'],'39')
        self.assertTrue(p['complete']);self.assertFalse(p['grants_execution_permission'])

    def test_forex_not_stock_turnover_unknown_stock_not_zero(self):
        self.add('fx',sec_type='CASH',symbol='EUR',shares=100000)
        self.add('untyped',sec_type='')
        self.add('foreign-stock',currency='EUR')
        p=self.project();self.assertEqual(p['gross_notional'],'0');self.assertFalse(p['complete'])
        self.assertEqual({x['exec_id'] for x in p['unresolved']},{'untyped','foreign-stock'})

    def test_explicit_timezone_day_boundary(self):
        self.add('late',time='2026-11-09T23:30:00-05:00')
        self.assertEqual(self.project()['gross_notional'],'80')
        self.assertEqual(self.project(zone='Europe/Berlin')['gross_notional'],'0')
        self.assertEqual(self.project(day='2026-11-10',zone='Europe/Berlin')['gross_notional'],'80')

    def test_missing_zone_and_dst_ambiguity_remain_unresolved(self):
        self.add('naive',time='20261109 09:31:00')
        self.assertFalse(self.project()['complete'])
        for text in ('20261101 01:30:00 America/New_York','20260308 02:30:00 America/New_York'):
            with self.assertRaises(ValueError):execution_instant(text)
        self.assertEqual(execution_instant('20261109 09:31:00 US/Eastern').hour,14)

    def test_historical_missing_timestamp_does_not_poison_every_future_day(self):
        self.add('historical',time='')
        self.assertTrue(self.project(day='2026-11-10')['complete'])
        self.assertFalse(self.project()['complete'])
