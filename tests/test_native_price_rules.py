import copy
import unittest
from decimal import localcontext
from trading.native_price_rules import floor_price,normalize_long_entry


class NativePriceRulesTests(unittest.TestCase):
    def setUp(self):
        self.proposal=dict(symbol='BAC',side='BUY',quantity=100,limit_price='10.049',stop_price='9.999')
        self.contract=dict(source='NATIVE_CONTRACT_DETAILS',complete=True,connection_generation='owned',
            sec_type='STK',currency='USD',symbol='BAC',con_id=123,observed_at='2026-11-10T00:00:00Z',
            valid_exchanges='SMART,NYSE',market_rule_ids='26,27')
        self.rule=dict(source='NATIVE_MARKET_RULE',complete=True,connection_generation='owned',
            observed_at='2026-11-10T00:00:00Z',market_rule_id=26,
            increments=[dict(low_edge='0',increment='0.01'),dict(low_edge='10',increment='0.05')])

    def run_terms(self):
        return normalize_long_entry(self.proposal,self.contract,self.rule,exchange='SMART',generation='owned',now=1794268801)

    def test_native_band_changes_wire_economics_without_authority(self):
        x=self.run_terms()
        self.assertEqual((x['limit_price'],x['stop_price'],x['notional_usd'],x['stop_distance_usd']),('10.00','9.99','1000.00','1.00'))
        self.assertTrue(x['requires_fee_and_risk_revalidation'])
        self.assertFalse(x['grants_trading_permission']);self.assertFalse(x['actual_fill_loss_bounded'])

    def test_result_rechecked_when_rounding_crosses_band(self):
        rows=[dict(low_edge='0',increment='0.03'),dict(low_edge='1.01',increment='0.1')]
        self.assertEqual(floor_price('1.02',rows),floor_price('0.999',rows))
        self.assertEqual(floor_price('1.02',rows),floor_price('0.99',rows))

    def test_ambiguous_or_unmapped_route_rejected(self):
        for fields in [dict(market_rule_ids='26'),dict(valid_exchanges='SMART,SMART'),dict(market_rule_ids='0,27'),dict(market_rule_ids='27,26')]:
            with self.subTest(fields=fields):
                saved=copy.deepcopy(self.contract);self.contract.update(fields)
                with self.assertRaises(PermissionError):self.run_terms()
                self.contract=saved

    def test_stale_foreign_incomplete_rule_never_uses_min_tick_fallback(self):
        for field,value in [('observed_at','2026-11-09T00:00:00Z'),('connection_generation','other'),('complete',False),('market_rule_id',True)]:
            with self.subTest(field=field):
                saved=copy.deepcopy(self.rule);self.rule[field]=value
                with self.assertRaises(PermissionError):self.run_terms()
                self.rule=saved

    def test_invalid_native_ladders_and_prices(self):
        for rows in [[],[dict(low_edge=1,increment='.01')],[dict(low_edge=0,increment=0)],
                [dict(low_edge=0,increment='.01'),dict(low_edge=0,increment='.1')]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):floor_price('10',rows)
        for value in [True,'NaN','Infinity',0,-1,'1e-13']:
            with self.subTest(value=value),self.assertRaises(ValueError):floor_price(value,self.rule['increments'])

    def test_stop_can_collapse_after_rounding_and_must_reject(self):
        self.proposal.update(limit_price='10.049',stop_price='10.001')
        with self.assertRaises(ValueError):self.run_terms()

    def test_wire_economics_remain_exact_under_small_caller_context(self):
        self.proposal.update(quantity=2147483647,limit_price='99999999999999999999.123456789012',stop_price='99999999999999999998.123456789012')
        self.rule['increments']=[dict(low_edge='0',increment='0.000000000001')]
        with localcontext() as ctx:
            ctx.prec=6
            result=self.run_terms()
        self.assertEqual(result['notional_usd'],'214748364699999999998117637788.514399286764')
        self.assertEqual(result['stop_distance_usd'],'2147483647.000000000000')

    def test_unsupported_quantity_size_is_rejected(self):
        self.proposal['quantity']=2147483648
        with self.assertRaises(PermissionError):self.run_terms()

    def test_numeric_bound_is_independent_of_caller_rounding(self):
        with localcontext() as ctx:
            ctx.prec=6
            with self.assertRaises(ValueError):floor_price('100000000000000000001',self.rule['increments'])
