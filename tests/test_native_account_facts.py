from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import unittest
from trading.native_account_facts import account_facts
from tests import test_native_cash_collector as cash_fixtures


class NativeAccountFactsTests(unittest.TestCase):
    def setUp(self):
        fixture = cash_fixtures.NativeCashCollectorTests()
        fixture.setUp()
        request = fixture.start()
        rows = fixture.rows()+[('NetLiquidation','1014994.80','EUR'),('BuyingPower','123456','EUR')]
        fixture.feed(request,rows)
        fixture.collector.end(request)
        self.now = fixture.now
        self.book = fixture.books[0]
        self.book.update(broker_epoch='epoch',broker_reconciled_at=self.now)
        self.state = dict(epoch='epoch',api_protocol={'connection':'owned-connection'},
            connected=True,identity=True,upstream_connected=True,dirty=False,
            ends=['orders','completed_orders','executions','positions'],reconciled_at=self.now,
            last_server_reply=self.now,native_server_clock=dict(valid=True,timestamp=int(self.now),
                received_at=self.now,connection_generation='owned-connection'))
        stamp=datetime.fromtimestamp(self.now,timezone.utc).isoformat()
        self.state['native_pnl']=dict(account='DUQ503649',source='NATIVE_ACCOUNT_PNL',
            grants_trading_permission=False,connection_generation='owned-connection',broker_epoch='epoch',
            admission_generation='epoch',started_at=stamp,observed_at=stamp,daily=0,unrealized=-12.5,realized=2)
        self.fingerprint()
    def fingerprint(self):
        self.state['currency_book_status']=dict(request_id=self.book['settlement_receipt']['request_id'],
            connection_generation='owned-connection',sha256=hashlib.sha256(json.dumps(self.book,
                ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest())
    def facts(self,**kwargs):
        return account_facts(self.book,self.state,now=kwargs.get('now',self.now),
            pnl_publication_blocked=kwargs.get('blocked',False))
    def test_complete_account_negative_settlement_and_real_pnl_zero_are_facts_only(self):
        facts=self.facts()
        self.assertEqual(facts['account']['net_liquidation']['currency'],'EUR')
        self.assertEqual(facts['pnl']['daily'],'0')
        self.assertIsNone(facts['pnl']['currency'])
        self.assertFalse(facts['pnl']['usable_for_monetary_limits'])
        self.assertEqual(facts['settlement']['currencies']['USD']['as_of_amount'],'-69788.66')
        self.assertFalse(facts['grants_trading_permission'])
    def test_missing_amount_wrong_unit_duplicate_or_unset_never_become_zero(self):
        original=deepcopy(self.book)
        for mode in ('missing','wrong_unit','duplicate','unset'):
            self.book=deepcopy(original)
            rows=self.book['settlement_receipt']['values']
            target=next(row for row in rows if row['key']=='BuyingPower')
            if mode=='missing':rows.remove(target)
            elif mode=='wrong_unit':target['currency']='BASE'
            elif mode=='duplicate':rows.append(dict(target))
            else:target['value']='1.7976931348623157e308'
            self.fingerprint()
            with self.assertRaises(ValueError):self.facts()
    def test_exact_file_fingerprint_is_required(self):
        self.book['available_funds']='99999'
        with self.assertRaises(PermissionError):self.facts()
    def test_connection_epoch_and_reconciliation_cannot_be_adopted_from_old_book(self):
        original=deepcopy(self.state)
        for field,value in (('epoch','replacement'),('reconciled_at',self.now+.1),('dirty',True),('identity',False)):
            self.state=deepcopy(original);self.state[field]=value
            with self.assertRaises(PermissionError):self.facts()
    def test_persisted_pnl_does_not_override_publication_fault(self):
        with self.assertRaises(PermissionError):self.facts(blocked=True)
        with self.assertRaises(PermissionError):self.facts(blocked=None)
    def test_missing_or_mixed_pnl_is_not_synthesized(self):
        original=deepcopy(self.state['native_pnl'])
        for field,value in (('daily',None),('daily',True),('daily',float('nan')),
                            ('account','OTHER'),('admission_generation','old'),('broker_epoch','old')):
            self.state['native_pnl']=dict(original);self.state['native_pnl'][field]=value
            with self.assertRaises((PermissionError,ValueError)):self.facts()
    def test_native_server_and_ledger_staleness_remain_independent(self):
        with self.assertRaises(PermissionError):self.facts(now=self.now+11)
        self.state['native_server_clock']['timestamp']=int(self.now)-20
        with self.assertRaises(PermissionError):self.facts()
    def test_cash_change_after_receipt_requires_new_native_read(self):
        self.state['latest_cash_change_at']=self.now+.1
        with self.assertRaises(PermissionError):self.facts()
