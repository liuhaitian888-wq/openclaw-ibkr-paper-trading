from types import SimpleNamespace as V
import unittest
from trading.currency_book import cashbook,paper_funding,PAPER_FINANCING

class CurrencyBookTests(unittest.TestCase):
 def rows(self):
  return [V(account='DU1',tag=t,currency=c,value=v) for t,c,v in (
    ('AvailableFunds','EUR','989550'),('TotalCashValue','EUR','945313'),
    ('$LEDGER-CashBalance','EUR','1000000'),('$LEDGER-CashBalance','USD','-69786.59'),
    ('$LEDGER-ExchangeRate','USD','.8904757'))]
 def test_currency_units_negative_balance_and_fx_direction_preserved(self):
  b=cashbook(self.rows(),'DU1');self.assertEqual(b['base_currency'],'EUR')
  self.assertEqual(b['currencies']['USD']['amount'],'-69786.59')
  self.assertTrue(b['currencies']['USD']['liability'])
  self.assertEqual(b['currencies']['USD']['value_in_base'],'-62143.262580863')
  f=paper_funding(b,PAPER_FINANCING)
  self.assertGreater(f['capacity_usd'],1000000);self.assertEqual(f['usd_cash'],-69786.59)
  self.assertFalse(f['automatic_fx_conversion_performed'])
  self.assertLess(paper_funding(b)['capacity_usd'],0)
 def test_missing_fx_is_unknown_not_one(self):
  rows=[r for r in self.rows() if r.tag!='$LEDGER-ExchangeRate']
  b=cashbook(rows,'DU1');self.assertIsNone(b['currencies']['USD']['rate_to_base'])
  with self.assertRaises(PermissionError):paper_funding(b,PAPER_FINANCING)
 def test_conflicting_alias_and_missing_currency_are_blocked(self):
  rows=self.rows()+[V(account='DU1',tag='CashBalance',currency='USD',value='1')]
  with self.assertRaises(ValueError):cashbook(rows,'DU1')
  rows=[r for r in self.rows() if not (r.tag=='$LEDGER-CashBalance' and r.currency=='USD')]
  with self.assertRaises(PermissionError):paper_funding(cashbook(rows,'DU1'))
 def test_no_cross_account_aggregation_or_zero_substitution(self):
  with self.assertRaises(ValueError):cashbook(self.rows(),'DU2')
  rows=self.rows();rows[0].value='NaN'
  with self.assertRaises(ValueError):cashbook(rows,'DU1')
