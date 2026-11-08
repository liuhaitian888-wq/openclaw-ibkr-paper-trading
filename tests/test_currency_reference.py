from datetime import datetime,timezone
import unittest
from trading.currency_book import convert_reference

class CurrencyReferenceTests(unittest.TestCase):
 def book(self):
  return {'source':'BROKER_API','account':'DUQ503649','base_currency':'EUR','observed_at':datetime.fromtimestamp(100,timezone.utc).isoformat(),'currencies':{'USD':{'currency':'USD','rate_to_base':'0.9'}}}
 def test_common_base_conversion_is_decimal_and_never_a_trade_quote(self):
  r=convert_reference(self.book(),'2000','USD','EUR',now=101)
  self.assertEqual(r['converted_amount'],'1800.0');self.assertFalse(r['executable_fx_quote'])
  self.assertEqual(convert_reference(self.book(),'1800','EUR','USD',now=101)['converted_amount'],'2000.000000000000000000000000')
 def test_stale_identity_missing_and_invalid_rates_fail_closed(self):
  for changes in [{'source':'MODEL'},{'account':'OTHER'},{'observed_at':datetime.fromtimestamp(0,timezone.utc).isoformat()}]:
   with self.subTest(changes=changes),self.assertRaises((ValueError,PermissionError)):
    convert_reference({**self.book(),**changes},2000,'USD','EUR',now=101)
  for rate in ['NaN','0','-1']:
   b=self.book();b['currencies']['USD']['rate_to_base']=rate
   with self.subTest(rate=rate),self.assertRaises(ValueError):convert_reference(b,2000,'USD','EUR',now=101)
  with self.assertRaises(KeyError):convert_reference(self.book(),2000,'GBP','EUR',now=101)
