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

class CashbookRequestTests(unittest.IsolatedAsyncioTestCase):
 async def test_explicit_ledger_is_cancelled_on_success_and_failure(self):
  import asyncio
  from trading.currency_book import fetch_paper_cashbook
  for failed in (False,True):
   with self.subTest(failed=failed):
    rows=CurrencyBookTests().rows();calls=[]
    future=asyncio.get_running_loop().create_future()
    if failed:future.set_exception(ConnectionError('Fixture disconnect'))
    else:future.set_result(None)
    class Client:
     def getReqId(self):return 17
     def reqAccountSummary(self,*args):calls.append(args)
     def cancelAccountSummary(self,req):calls.append(('cancel',req))
    class IB:
     client=Client()
     wrapper=V(startReq=lambda req:future,acctSummary={i:r for i,r in enumerate(rows)})
     def managedAccounts(self):return ['DU1']
     def isConnected(self):return True
     async def accountSummaryAsync(self,account):return []
    if failed:
     with self.assertRaises(ConnectionError):await fetch_paper_cashbook(IB(),'DU1')
    else:self.assertEqual((await fetch_paper_cashbook(IB(),'DU1'))['currencies']['USD']['amount'],'-69786.59')
    self.assertEqual(calls,[(17,'All','$LEDGER:USD'),('cancel',17)])

 async def test_missing_eur_cash_is_explicitly_requested_not_inferred_from_base_totals(self):
  import asyncio
  from trading.currency_book import fetch_paper_cashbook
  rows=[r for r in CurrencyBookTests().rows() if not (r.currency=='EUR' and r.tag=='$LEDGER-CashBalance')]
  cache={i:r for i,r in enumerate(rows)};futures={};calls=[]
  class Client:
   next_id=20
   def getReqId(self):self.next_id+=1;return self.next_id
   def reqAccountSummary(self,req,group,tags):
    calls.append((req,tags))
    if tags=='$LEDGER:EUR':cache[99]=V(account='DU1',tag='CashBalance',currency='EUR',value='1000000')
    futures[req].set_result(None)
   def cancelAccountSummary(self,req):calls.append(('cancel',req))
  def start(req):futures[req]=asyncio.get_running_loop().create_future();return futures[req]
  class IB:
   client=Client();wrapper=V(startReq=start,acctSummary=cache)
   def managedAccounts(self):return ['DU1']
   def isConnected(self):return True
   async def accountSummaryAsync(self,account):return []
  b=await fetch_paper_cashbook(IB(),'DU1')
  self.assertEqual(b['currencies']['EUR']['amount'],'1000000')
  self.assertNotEqual(b['currencies']['EUR']['amount'],b['total_cash_value'])
  self.assertEqual(calls,[(21,'$LEDGER:USD'),('cancel',21),(22,'$LEDGER:EUR'),('cancel',22)])
  self.assertEqual(b['currency_coverage'],'USD_AND_BASE_VERIFIED')
