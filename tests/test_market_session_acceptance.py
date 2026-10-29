import unittest
from ops.cloud.market_session_acceptance import evaluate,verdict

class PassiveAcceptanceTests(unittest.TestCase):
 def test_frozen_delayed_never_pass_even_with_new_receive_timestamps(self):
  for kind in (2,3,4):
   state={'quotes':{s:dict(bid=1,ask=2,bid_at=100,ask_at=100,data_type=kind) for s in ('PFE','BAC','KO')}}
   out=evaluate(state,{},100,True)
   self.assertTrue(all(not x['health']['allows_realtime'] for x in out.values()))
 def test_repeated_snapshots_are_not_distinct_quotes_or_complete_recovery(self):
  state={'quotes':{s:dict(bid=1,ask=2,bid_at=100,ask_at=100,data_type=1) for s in ('PFE','BAC','KO')}}
  sample=dict(observed_at=400,connected=True,identity=True,symbols=evaluate(state,{},400,True))
  r=verdict([sample]*12,0,1000)
  self.assertEqual(r['overall'],'FAIL')
  self.assertTrue(all(v['status']=='PENDING' for v in r['real_recovery'].values()))
 def test_closed_window_and_missing_bars_stay_pending(self):
  r=verdict([dict(observed_at=0,symbols={})],100,1000)
  self.assertEqual(r['overall'],'PENDING')
 def test_contiguous_bars_and_distinct_fresh_observations_pass_data_only(self):
  rows=[]
  for now in range(300,420,5):
   state={'quotes':{s:dict(bid=1,ask=2,bid_at=now,ask_at=now,data_type=1) for s in ('PFE','BAC','KO')},'bars':{s:[now//60*60-120,now//60*60-60,now//60*60] for s in ('PFE','BAC','KO')}}
   rows.append(dict(observed_at=now,connected=True,identity=True,source_commit='fixed-version',ownership={'single_owner_verified':True},symbols=evaluate(state,{},now,True)))
  r=verdict(rows,0,1000);self.assertEqual(r['overall'],'PASS')
  self.assertTrue(all(v['status']=='PENDING' for v in r['real_recovery'].values()))

 def samples(self,end=660,missing=(),frozen=False):
  rows=[]
  for now in range(300,end,5):
   bars=[t for t in range(60,now//60*60+1,60) if t not in missing]
   if frozen:bars=[120,180,240]
   state={'quotes':{s:dict(bid=1,ask=2,bid_at=now,ask_at=now,last=1.5,last_at=now,data_type=1) for s in ('PFE','BAC','KO')},'bars':{s:bars for s in ('PFE','BAC','KO')}}
   rows.append(dict(observed_at=now,connected=True,identity=True,source_commit='fixed-version',ownership={'single_owner_verified':True},symbols=evaluate(state,{},now,True)))
  return rows
 def test_old_three_bars_cannot_pass_after_updates_stop(self):
  result=verdict(self.samples(frozen=True),0,1000)
  self.assertTrue(all(s['kline_status']=='FAIL' for s in result['symbols'].values()))
 def test_missing_mature_minute_is_not_hidden_by_fresh_tail(self):
  result=verdict(self.samples(missing=(360,)),0,1000)
  self.assertTrue(all(s['kline_status']=='FAIL' and 360 in s['missing_completed_ends'] for s in result['symbols'].values()))
 def test_full_observed_mature_sequence_and_last_diagnostics(self):
  result=verdict(self.samples(),0,1000)
  self.assertEqual(result['overall'],'PASS')
  self.assertTrue(all(s['last_timestamp_status']=='OBSERVED_FRESH' and s['actual_market_data_types']=={'1':72} for s in result['symbols'].values()))
 def test_verified_history_proof_is_used_without_five_second_bars(self):
  state={'history_evidence':{'PFE':dict(complete=True,completed_ends=[120,180,240])}}
  self.assertEqual(evaluate(state,{},250,True)['PFE']['bar_ends'],[120,180,240])
  state['history_evidence']['PFE']['complete']=False
  self.assertEqual(evaluate(state,{},250,True)['PFE']['bar_ends'],[])
 def test_version_change_cannot_claim_fixed_version_acceptance(self):
  rows=self.samples();rows[-1]['source_commit']='different-version'
  result=verdict(rows,0,1000)
  self.assertTrue(result['production_version_changed']);self.assertEqual(result['overall'],'FAIL')
 def test_unknown_or_duplicate_owner_cannot_pass_with_healthy_market_data(self):
  for ownership in ({},{'single_owner_verified':False}):
   rows=self.samples();rows[-1]['ownership']=ownership
   result=verdict(rows,0,1000)
   self.assertEqual(result['owner_status'],'FAIL');self.assertEqual(result['overall'],'FAIL')
 def test_read_error_cannot_be_hidden_by_healthy_remaining_samples(self):
  rows=self.samples();rows.append(dict(observed_at=661,read_error='Unavailable'))
  self.assertEqual(verdict(rows,0,1000)['overall'],'FAIL')
