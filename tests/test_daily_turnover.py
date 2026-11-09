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

    def test_partial_fill_not_double_counted_and_live_commitment_crosses_day(self):
        from trading.entry_admission import initialize_claims
        from trading.daily_turnover import admission_usage
        from trading.models import TradeProposal
        p=TradeProposal(symbol='BAC',side='BUY',quantity=10,limit_price=40,stop_price=39,idempotency_key='bound')
        self.audit.reserve(p,'PAPER_TRANSMIT','strategy')
        parent=dict(account='DUQ503649',perm_id=1,symbol='BAC',currency='USD',sec_type='STK',con_id=123,order_ref='bound',quantity=10,limit_price=40)
        self.add('partial',shares=2,order_ref='bound')
        with closing(self.audit._connect()) as c,c:
            initialize_claims(c)
            c.execute("INSERT INTO entry_native_bindings VALUES(?,1,?,?)",('bound','2026-11-09T14:30:00+00:00',json.dumps({'parent':parent})))
            c.execute("INSERT INTO entry_cash_claims VALUES(?,'DUQ503649','TRANSFERRED_TO_BROKER_ORDER','0','5',?,?,?,?)",('bound','now','now','epoch','{}'))
            today=admission_usage(c,'2026-11-09','America/New_York')
            tomorrow=admission_usage(c,'2026-11-10','America/New_York')
            self.assertEqual(today['gross_notional'],'80');self.assertEqual(today['entry_budget_used'],'400')
            self.assertEqual(tomorrow['entry_budget_used'],'320')
            c.execute("UPDATE entry_cash_claims SET state='BROKER_ACCOUNTED_FEE_HELD'")
            self.assertEqual(admission_usage(c,'2026-11-09','America/New_York')['entry_budget_used'],'80')
            self.assertEqual(admission_usage(c,'2026-11-10','America/New_York')['entry_budget_used'],'0')

    def test_failed_label_after_transport_does_not_erase_daily_commitment(self):
        from trading.daily_turnover import admission_usage
        from trading.models import TradeProposal
        p=TradeProposal(symbol='BAC',side='BUY',quantity=2,limit_price=40,stop_price=39,idempotency_key='uncertain')
        self.audit.reserve(p,'PAPER_TRANSMIT','strategy')
        self.audit.mark_submission_started('uncertain');self.audit.update('uncertain','FAILED','not native no-send proof')
        with closing(self.audit._connect()) as c:
            day=datetime.now(timezone.utc).date().isoformat()
            self.assertEqual(admission_usage(c,day,'UTC')['outstanding_commitments'],'80')

    def test_health_budget_never_presents_unverified_turnover_as_zero(self):
        self.add('missing-time',time='')
        report=self.audit.daily_entry_budget_report('2026-11-09','America/New_York')
        self.assertFalse(report['admission_reconciled'])
        self.assertIsNone(report['entry_budget_used'])
        self.assertEqual(report['unresolved'][0]['exec_id'],'missing-time')

    def test_corrected_exec_ids_are_not_counted_as_independent_fills(self):
        self.add('broker.partial.01');self.add('broker.partial.02',price=41)
        p=self.project();self.assertFalse(p['complete']);self.assertEqual(p['gross_notional'],'0')
        self.assertEqual(len(p['unresolved']),2)
        self.assertTrue(all(x['reason']=='EXECUTION_CORRECTION_REQUIRES_RECONCILIATION' for x in p['unresolved']))

    def test_orphan_correction_and_non_numeric_ids_are_distinct(self):
        self.add('orphan.03');self.add('opaque-id')
        p=self.project();self.assertFalse(p['complete']);self.assertEqual(p['gross_notional'],'80')
        self.assertEqual(p['unresolved'][0]['exec_id'],'orphan.03')
