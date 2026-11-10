import unittest
from types import SimpleNamespace as NS
from trading.native_contract_qualifier import NativeContractQualifier
from trading.native_price_rules import normalize_long_entry


class NativeContractQualifierTests(unittest.TestCase):
    def setUp(self):
        self.now=1794268800.;self.elapsed=0.;self.calls=[]
        self.admission=dict(account='DUQ503649',environment='PAPER',connection_generation='g')
        self.client=NS(isConnected=lambda:True,reqContractDetails=lambda *x:self.calls.append(('contract',x)),
                       reqMarketRule=lambda *x:self.calls.append(('rule',x)))
        self.actor=NativeContractQualifier(self.client,generation='g',admitted=lambda:self.admission,
            allocate_request_id=lambda:123,clock=lambda:self.now,monotonic=lambda:self.elapsed)
        self.contract=NS(symbol='BAC',exchange='SMART',secType='STK',currency='USD',conId=111,primaryExchange='NYSE')
        self.details=NS(contract=self.contract,minTick=.01,validExchanges='SMART,NYSE',marketRuleIds='26,27')

    def start(self):self.actor.start(self.contract)
    def complete_contract(self):
        self.start();self.assertTrue(self.actor.contract_details(123,self.details));self.assertTrue(self.actor.contract_end(123))

    def test_single_owned_read_only_occurrence_yields_typed_fresh_rules(self):
        self.complete_contract()
        self.assertIsNone(self.actor.result())
        self.assertTrue(self.actor.market_rule(26,[NS(lowEdge=0,increment=.01)]))
        result=self.actor.result();self.assertFalse(result['grants_trading_permission'])
        terms=normalize_long_entry(dict(symbol='BAC',side='BUY',quantity=1,limit_price='20.123',stop_price='19.123'),
            result['contract'],result['rule'],exchange='SMART',generation='g',now=self.now)
        self.assertEqual(terms['limit_price'],'20.12')
        result['contract']['con_id']=999
        self.assertEqual(self.actor.result()['contract']['con_id'],111)
        self.assertEqual([x[0] for x in self.calls],['contract','rule'])
        with self.assertRaises(PermissionError):self.start()

    def test_ambiguous_details_never_requests_rule(self):
        self.start();self.actor.contract_details(123,self.details);self.actor.contract_details(123,self.details)
        self.assertEqual(self.actor.phase,'FAILED');self.assertFalse(self.actor.contract_end(123))
        self.assertEqual(len(self.calls),1)

    def test_foreign_request_and_early_rule_are_ignored(self):
        self.start()
        self.assertFalse(self.actor.contract_details(124,self.details))
        self.assertFalse(self.actor.market_rule(26,[NS(lowEdge=0,increment=.01)]))
        self.assertFalse(self.actor.contract_end(124));self.assertIsNone(self.actor.result())

    def test_owner_change_invalidates_already_complete_result(self):
        self.complete_contract();self.actor.market_rule(26,[NS(lowEdge=0,increment=.01)])
        self.admission['connection_generation']='new'
        self.assertIsNone(self.actor.result());self.assertEqual(self.actor.phase,'FAILED')
        self.assertEqual(len(self.calls),2)

    def test_timeout_no_retry_and_close_does_not_disconnect_peer(self):
        self.start();self.elapsed=8;self.actor.poll()
        self.assertEqual(self.actor.failure,'QUALIFICATION_TIMEOUT')
        with self.assertRaises(PermissionError):self.start()
        self.actor.close();self.assertFalse(self.actor.contract_details(123,self.details))
        self.assertEqual(len(self.calls),1)

    def test_missing_contract_end_or_invalid_ladder_never_complete(self):
        self.start();self.actor.contract_details(123,self.details)
        self.assertIsNone(self.actor.result());self.assertEqual(len(self.calls),1)
        self.actor.contract_end(123)
        self.actor.market_rule(26,[NS(lowEdge=1,increment=.01)])
        self.assertEqual(self.actor.phase,'FAILED');self.assertIsNone(self.actor.result())

    def test_native_send_exception_consumes_single_attempt(self):
        def failed(*_):raise OSError('response uncertainty')
        self.client.reqContractDetails=failed;self.start()
        self.assertEqual(self.actor.phase,'FAILED')
        with self.assertRaises(PermissionError):self.start()
