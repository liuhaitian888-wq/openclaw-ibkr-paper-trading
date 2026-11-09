import copy
import unittest
from trading.instrument_facts import instrument_kind,portfolio_facts,enrich_execution


class InstrumentFactsTests(unittest.TestCase):
    def test_negative_fx_pair_is_retained_but_is_not_cash_or_stock_short(self):
        state={'positions':{'AAPL':17,'EUR':-64414},'contracts':{'AAPL':{'con_id':1,'currency':'USD','sec_type':'STK'},'EUR':{'con_id':12087792,'currency':'USD','sec_type':'CASH'}}}
        original=copy.deepcopy(state);facts=portfolio_facts(state,verified=True)
        self.assertEqual(state,original)
        self.assertEqual([x['symbol'] for x in facts['securities']],['AAPL'])
        self.assertEqual(facts['fx_pair_positions'][0]['quantity'],-64414)
        self.assertFalse(facts['actual_cash_balances_inferred'])
        self.assertFalse(facts['grants_trading_permission'])
        self.assertEqual(instrument_kind('EUR',{'con_id':1,'currency':'USD','sec_type':'STK'}),'SECURITY')

    def test_incomplete_or_unsupported_currency_identity_is_never_dropped(self):
        for contract in ({'con_id':0,'currency':'USD','sec_type':'CASH'}, {'con_id':True,'currency':'USD','sec_type':'CASH'}, {'con_id':12,'currency':'EUR','sec_type':'CASH'}, {'con_id':12,'currency':'ZZZ','sec_type':'CASH'}, {'con_id':12,'currency':'USD','sec_type':'CFD'}):
            with self.subTest(contract=contract):
                facts=portfolio_facts({'positions':{'EUR':-2},'contracts':{'EUR':contract}},verified=False)
                self.assertEqual(len(facts['unsupported']),1)
                self.assertEqual(facts['fx_pair_positions'],[])
                self.assertFalse(facts['broker_snapshot_verified'])

    def test_duplicate_execution_only_enriches_missing_instrument_evidence(self):
        old={'exec_id':'x','account':'DUQ503649','symbol':'EUR','side':'SLD','shares':64414,'price':1.1}
        typed={**old,'con_id':12087792,'currency':'USD','sec_type':'CASH'}
        self.assertEqual(enrich_execution(old,typed),typed)
        self.assertEqual(enrich_execution(typed,old),typed)
        for changed in ({**typed,'price':1.2},{**typed,'side':'BOT'},{**typed,'con_id':99},{**typed,'account':'OTHER'}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):enrich_execution(typed,changed)
