import unittest
from unittest.mock import patch,Mock
from trading.gateway_recovery import decide,ACCOUNT,ENDS
from ops.cloud import gateway_watchdog as watchdog

class GatewayRecoveryTests(unittest.TestCase):
 def healthy(self,t):
  return dict(approved=True,hold=False,service='active',generation='1:100',auth_required=False,identity_mismatch=False,
   native=dict(connected=True,identity=True,upstream_connected=True,last_server_reply=t,dirty=False,ends=list(ENDS)),
   readback=dict(complete=True,account_id=ACCOUNT,environment='PAPER',at=t,server_time=t,gateway_api_handshake=True))
 def failed(self,t):
  e=self.healthy(t);e['native']['last_server_reply']=0;e['readback'].update(complete=False,gateway_api_handshake=False);return e
 def reserved(self):
  s={}
  for t in (1000,1300,1600,1900):s,a=decide(s,self.failed(t),t)
  self.assertEqual(a,'RESTART_RESERVED');return s
 def test_market_closed_and_upstream_loss_do_not_restart_responsive_api(self):
  s={}
  for t in range(1000,5000,30):
   e=self.healthy(t);e['native']['upstream_connected']=False;e['readback']['complete']=False
   s,a=decide(s,e,t);self.assertEqual(a,'NONE')
  self.assertEqual(s['reason'],'UPSTREAM_OR_RECONCILIATION_WAIT')
 def test_local_protocol_response_prevents_restart_even_when_upstream_heartbeat_missing(self):
  s={}
  for t in (1000,2000,3000):
   e=self.failed(t);e['readback']['gateway_api_handshake']=True;s,a=decide(s,e,t)
   self.assertEqual(a,'NONE');self.assertEqual(s['reason'],'LOCAL_API_RESPONSIVE_UPSTREAM_WAIT')
 def test_hang_requires_two_independent_failures_stable_generation_and_15_minutes(self):
  s={}
  for t in (1000,1300,1600):
   s,a=decide(s,self.failed(t),t);self.assertEqual(a,'NONE')
  s,a=decide(s,self.failed(1900),1900);self.assertEqual(a,'RESTART_RESERVED');self.assertEqual(s['operation'],'STARTED')
 def test_no_repeat_for_started_unknown_outcome_or_new_process_without_readback(self):
  s=self.reserved()
  for t in (1930,2530,90000):
   e=self.failed(t);e['generation']='2:200'
   s,a=decide(s,e,t);self.assertEqual(a,'NONE')
  self.assertEqual(s['operation'],'OPERATOR_REQUIRED')
 def test_recovery_needs_new_generation_two_fresh_readbacks_and_stable_60_seconds(self):
  s=self.reserved();s,a=decide(s,self.healthy(2000),2000)
  self.assertNotEqual(s['operation'],'RECOVERED')
  e=self.healthy(2030);e['generation']='2:200';s,a=decide(s,e,2030)
  self.assertEqual(s['reason'],'VERIFYING_RECOVERY')
  e=self.healthy(2090);e['generation']='2:200';s,a=decide(s,e,2090)
  self.assertEqual(s['operation'],'RECOVERED');self.assertEqual(a,'NONE')
  # Persistent 24h budget still blocks a later confirmed hang.
  for t in (2200,2500,2800,3100):
   e=self.failed(t);e['generation']='2:200';s,a=decide(s,e,t)
  self.assertEqual(a,'NONE');self.assertEqual(s['reason'],'DAILY_RESTART_BUDGET_EXHAUSTED')
 def test_auth_identity_hold_and_unavailable_evidence_never_restart(self):
  for field,value in (('auth_required',True),('identity_mismatch',True),('hold',True),('approved',False),('service','inactive'),('generation',None)):
   s={}
   for t in (1000,2000,3000):
    e=self.failed(t);e[field]=value;s,a=decide(s,e,t);self.assertEqual(a,'NONE')
  for t in (1000,2000,3000):
   e=self.failed(t);e['readback']['at']=0;s,a=decide({},e,t);self.assertEqual(a,'NONE')
 def test_repeated_same_failure_snapshot_cannot_supply_two_failures(self):
  s={}
  for t in (1000,1300,1600,1900):
   e=self.failed(t);e['readback']['at']=1000;s,a=decide(s,e,t);self.assertEqual(a,'NONE')
 def test_hang_event_is_ops_but_never_public_in_shared_group(self):
  from reporting.notification_center import category,audience
  item={'kind':'ALERT','incident_key':'gateway-hang','payload':{'scope':'GATEWAY_HANG'}}
  self.assertEqual(category(item),'ops')
  self.assertEqual(audience(item,{'audience_mode':'shared_group'}),'owner')
 def test_supervisor_targets_only_fixed_unit_after_generation_recheck(self):
  request=dict(action='RESTART_RESERVED',generation='1:100')
  with patch.object(watchdog.os,'geteuid',return_value=0),patch.object(watchdog,'delegate',return_value=request),patch.object(watchdog,'gateway_generation',return_value='1:100'),patch.object(watchdog,'unit',return_value={'ActiveState':'active'}),patch.object(watchdog.subprocess,'run') as run:
   result=watchdog.supervise();self.assertEqual(result['action'],'RESTART_SUBMITTED_REQUIRES_READBACK')
   self.assertEqual(run.call_args.args[0],['/usr/bin/systemctl','--no-block','restart','ibkr-gateway.service'])
  with patch.object(watchdog.os,'geteuid',return_value=0),patch.object(watchdog,'delegate',return_value={'action':'RESTART_RESERVED','generation':'1:100'}),patch.object(watchdog,'gateway_generation',return_value='2:200'),patch.object(watchdog.subprocess,'run') as run:
   self.assertEqual(watchdog.supervise()['action'],'HELD_AFTER_RESERVATION');run.assert_not_called()

if __name__=='__main__':unittest.main()
