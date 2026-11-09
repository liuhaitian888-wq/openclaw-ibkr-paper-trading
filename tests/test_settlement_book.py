import copy
import unittest
from trading.settlement_book import schedule,settlement_book

class SettlementBookTests(unittest.TestCase):
    def receipt(self):
        return dict(source='NATIVE_ACCOUNT_UPDATE_MULTI',account='DUQ503649',request_id=18996,complete=True,started_at='2026-11-09T20:42:00+00:00',finished_at='2026-11-09T20:42:01+00:00',values=[
            dict(account='DUQ503649',model='',key='AccountReady',value='true',currency=''),
            dict(account='DUQ503649',model='',key='SettledCashByDate',value='20261109:-69788.66;20261112:2019.42306',currency='USD'),
            dict(account='DUQ503649',model='',key='SettledCashByDate',value='20261109:1007454.60504;20261112:943040.60504',currency='EUR'),
            dict(account='DUQ503649',model='',key='SettledCashByDate',value='20261109:945259.9164251678;20261112:944840.2869424511446',currency='BASE')])
    def parse(self,receipt=None,day='2026-11-09'):
        return settlement_book(receipt or self.receipt(),account='DUQ503649',base_currency='EUR',as_of_day=day)
    def test_future_cumulative_balance_not_spendable_now_or_extra_inflow(self):
        b=self.parse();self.assertEqual(b['currencies']['USD']['as_of_amount'],'-69788.66')
        self.assertEqual(self.parse(day='2026-11-12')['currencies']['USD']['as_of_amount'],'2019.42306')
        self.assertFalse(b['grants_execution_permission']);self.assertFalse(b['stock_value_date_verified'])
        self.assertNotEqual(b['base_projections']['SettledCashByDate']['2026-11-09'],b['currencies']['EUR']['as_of_amount'])
    def test_missing_explicit_usd_is_not_replaced_with_base_or_zero(self):
        r=self.receipt();r['values']=[x for x in r['values'] if x['currency']!='USD']
        with self.assertRaises(PermissionError):self.parse(r)
        self.assertIsNone(self.parse(day='2026-11-08')['currencies']['USD']['as_of_amount'])
    def test_mixed_account_not_ready_unended_and_conflicting_rows_rejected(self):
        for change in ('account','ready','end','conflict'):
            r=self.receipt()
            if change=='account':r['values'][1]['account']='OTHER'
            if change=='ready':r['values'][0]['value']='false'
            if change=='end':r['complete']=False
            if change=='conflict':r['values'].append({**r['values'][1],'value':'20261109:999'})
            with self.subTest(change=change),self.assertRaises((ValueError,PermissionError)):self.parse(r)
    def test_malformed_nonfinite_and_duplicate_dates_rejected(self):
        for raw in ('20261109:NaN','20261109:Infinity','20261301:1','20261109:1;20261109:2','2026-11-09:1',''):
            with self.subTest(raw=raw),self.assertRaises((ValueError,ArithmeticError)):schedule(raw)

    def test_noncanonical_evaluation_date_is_not_compared_lexically(self):
        with self.assertRaises(ValueError):self.parse(day='20261109')
