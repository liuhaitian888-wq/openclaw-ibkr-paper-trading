from copy import deepcopy
import unittest
from trading.symbol_health import compute_pause_scopes,SYSTEMIC_PAUSE_FACTS

class ScopedPauseTests(unittest.TestCase):
    def setUp(self):
        self.now=1000
        self.health={s:dict(status='REALTIME_HEALTHY',allows_realtime=True,observed_at=1000,reason='fresh') for s in ('A','B','C')}
        self.system={k:True for k in SYSTEMIC_PAUSE_FACTS}
        self.bars={s:True for s in self.health};self.risk=dict(self.bars)
        self.deps={'independent':{s:(s,) for s in self.health},'shared':{'A':('A','B'),'C':('B','C')}}
    def compute(self):
        return compute_pause_scopes(self.health,self.deps,self.system,now=self.now,kline_ready=self.bars,symbol_risk=self.risk)
    def fail(self,symbol):
        self.health[symbol].update(status='UNKNOWN',allows_realtime=False,reason='IBKR 10197')
    def test_single_symbol_isolated_but_shared_strategy_dependencies_block(self):
        self.fail('B');p=self.compute()
        self.assertFalse(p['global_new_orders_paused'])
        self.assertTrue(p['decisions']['independent']['A']['allowed'])
        self.assertFalse(p['decisions']['independent']['B']['allowed'])
        self.assertTrue(p['decisions']['independent']['C']['allowed'])
        self.assertTrue(all(not d['allowed'] for d in p['decisions']['shared'].values()))
        self.assertTrue(any(r['scope']=='STRATEGY_PAUSED' for r in p['pauses']))
        self.assertTrue(all(all(k in r for k in ('affected_symbols','affected_strategies','reason','scope','recovery_conditions')) for r in p['pauses']))
    def test_multiple_and_all_data_failures_never_imply_l3(self):
        self.fail('A');self.fail('B');p=self.compute()
        self.assertFalse(p['global_new_orders_paused']);self.assertTrue(p['decisions']['independent']['C']['allowed'])
        self.fail('C');p=self.compute()
        self.assertFalse(p['global_new_orders_paused'])
        self.assertTrue(all(not d['allowed'] for d in p['decisions']['independent'].values()))
        self.assertNotIn('GLOBAL_NEW_ORDERS_PAUSED',[r['scope'] for r in p['pauses']])
    def test_only_systemic_failures_create_global_pause(self):
        for key in SYSTEMIC_PAUSE_FACTS:
            with self.subTest(key=key):
                old=self.system[key];self.system[key]=False;p=self.compute();self.system[key]=old
                self.assertTrue(p['global_new_orders_paused']);self.assertIn(key,p['global_reasons'])
                self.assertTrue(all(not d['allowed'] for rows in p['decisions'].values() for d in rows.values()))
    def test_recovery_needs_quote_bar_and_order_risk_checks(self):
        self.fail('B');self.assertFalse(self.compute()['decisions']['independent']['B']['allowed'])
        self.health['B'].update(status='REALTIME_HEALTHY',allows_realtime=True)
        self.bars['B']=False;self.assertFalse(self.compute()['decisions']['independent']['B']['allowed'])
        self.bars['B']=True;self.risk['B']=False;self.assertFalse(self.compute()['decisions']['independent']['B']['allowed'])
        self.risk['B']=True;self.assertTrue(self.compute()['decisions']['independent']['B']['allowed'])
        self.now+=6;self.assertFalse(self.compute()['decisions']['independent']['B']['allowed'])
    def test_environment_pairs_share_identical_impact_calculation(self):
        self.fail('B')
        reference=self.compute()
        for pair in ('Live/Paper','Live/Live','Paper/Paper'):
            self.system['session_pair']=pair
            self.assertEqual(self.compute(),reference)
        self.assertEqual(reference['existing_protection_action'],'PRESERVE; no cancel/modify from market pause')
        self.assertIn('market_recovery',reference['maintenance_continues'])
