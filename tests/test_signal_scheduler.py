from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock
from strategies import MarketData,PortfolioState
from trading.signal_scheduler import SignalScheduler,StrategyBinding,catalog_bindings
from trading.symbol_health import classify_symbol

class SignalSchedulerTests(unittest.TestCase):
 def setUp(self):
  self.now=1000;self.portfolio=PortfolioState(cash=0,equity=0,positions={})
  self.inputs={s:MarketData(s,list(range(80,101)),datetime.fromtimestamp(1000,timezone.utc),100,101,{'ml_up_probability':.7}) for s in ('GOOD','BAD')}
  self.health={s:classify_symbol(dict(data_type=1,bid=100,ask=101,bid_at=1000,ask_at=1000),1000,session='REGULAR') for s in self.inputs}
  configs={name:dict(symbols=['GOOD','BAD'],parameters=params) for name,params in (
   ('dual_moving_average',{}),('zscore_mean_reversion',{}),('grid_rebalance',{'reference_price':110}),('lightgbm_style_baseline',{}))}
  self.bindings=catalog_bindings(configs);self.scheduler=SignalScheduler(self.bindings)
 def test_all_real_strategies_keep_universe_and_isolate_bad_symbol(self):
  self.health['BAD']=classify_symbol({'data_type':3},1000,session='REGULAR')
  result=self.scheduler.run('cycle1',self.inputs,self.health,self.portfolio)
  self.assertEqual(len(result['strategies_scheduled']),4);self.assertEqual(len(result['results']),8)
  self.assertTrue(all(r['status']=='EVALUATED' for r in result['results'] if r['symbol']=='GOOD'))
  self.assertTrue(all(r['status']=='SKIPPED' and r['signal'] is None for r in result['results'] if r['symbol']=='BAD'))
  self.assertFalse(result['execution_enabled']);self.assertTrue(all(not r['eligible_to_submit'] for r in result['results']))
 def test_every_unreliable_state_skips_only_target(self):
  for i,state in enumerate(('REALTIME_STALE','UNKNOWN','DELAYED','FROZEN','DELAYED_FROZEN','PERMISSION_DENIED')):
   self.health['BAD']={'status':state,'allows_realtime':False,'reason':state}
   rows=self.scheduler.run(str(i),self.inputs,self.health,self.portfolio)['results']
   self.assertEqual(sum(r['status']=='EVALUATED' for r in rows),4)
 def test_duplicate_cycle_conflict_and_external_execution_switch_independence(self):
  evaluator=Mock(wraps=self.bindings[0].evaluator)
  scheduler=SignalScheduler([StrategyBinding('dual_moving_average',('GOOD',),evaluator)])
  first=scheduler.run('one',self.inputs,self.health,self.portfolio)
  self.assertEqual(first,scheduler.run('one',self.inputs,self.health,self.portfolio));self.assertEqual(evaluator.generate_signal.call_count,1)
  first['results'].clear();self.assertEqual(len(scheduler.run('one',self.inputs,self.health,self.portfolio)['results']),1)
  self.health['GOOD']['status']='UNKNOWN'
  with self.assertRaises(ValueError):scheduler.run('one',self.inputs,self.health,self.portfolio)
 def test_strategy_exception_does_not_stop_peers_or_other_symbols(self):
  failing=Mock();failing.generate_signal.side_effect=RuntimeError('broken')
  scheduler=SignalScheduler([StrategyBinding('broken',('BAD',),failing),self.bindings[0]])
  rows=scheduler.run('one',self.inputs,self.health,self.portfolio)['results']
  self.assertEqual(rows[0]['reason'],'STRATEGY_ERROR_RuntimeError');self.assertEqual(rows[-1]['status'],'EVALUATED')
 def test_missing_config_and_ml_feature_are_explicit_not_fabricated(self):
  bindings=catalog_bindings({},('GOOD','BAD'));self.assertEqual(len(bindings),4)
  rows=SignalScheduler(bindings).run('one',self.inputs,self.health,self.portfolio)['results']
  self.assertTrue(all(r['reason']=='STRATEGY_CONFIGURATION_NOT_PROVIDED' for r in rows))
  self.inputs['BAD']=replace(self.inputs['BAD'],features={})
  rows=self.scheduler.run('two',self.inputs,self.health,self.portfolio)['results']
  self.assertEqual([r['reason'] for r in rows if r['strategy']=='lightgbm_style_baseline' and r['symbol']=='BAD'],['ML_FEATURE_MISSING'])
 def test_major_data_fault_blocks_compute_but_retains_all_schedule_rows(self):
  result=self.scheduler.run('one',self.inputs,self.health,self.portfolio,global_data_fault='ACCOUNT_IDENTITY_UNVERIFIED')
  self.assertEqual(len(result['results']),8);self.assertTrue(all(r['status']=='SKIPPED' for r in result['results']))
 def test_custom_strategy_scope_is_not_trimmed_to_diagnostic_watchlist(self):
  cfg={'dual_moving_average':dict(symbols=['GOOD','BAD','OTHER'])}
  bindings=catalog_bindings(cfg,('GOOD',))
  rows=SignalScheduler(bindings).run('one',self.inputs,self.health,self.portfolio)['results']
  other=[r for r in rows if r['symbol']=='OTHER'];self.assertEqual(len(other),1);self.assertEqual(other[0]['status'],'SKIPPED')

 def test_invalid_configuration_and_unknown_adapter_do_not_stop_complete_strategy(self):
  cfg={'dual_moving_average':dict(symbols=['GOOD']), 'grid_rebalance':dict(symbols=['BAD']),
       'preserved_future_strategy':dict(symbols=['OTHER'])}
  scheduler=SignalScheduler(catalog_bindings(cfg,('GOOD','BAD')))
  result=scheduler.run('one',self.inputs,self.health,self.portfolio)
  self.assertIn('preserved_future_strategy',result['strategies_scheduled'])
  self.assertEqual(result['strategy_states']['grid_rebalance']['state'],'CONFIG_MISSING')
  good=[r for r in result['results'] if r['strategy']=='dual_moving_average']
  self.assertEqual(good[0]['status'],'EVALUATED')
