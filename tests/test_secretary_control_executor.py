from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize,accept_update
from reporting.secretary_controls import pending_controls
from ops.cloud.secretary_control_executor import process_gateway_controls


class CloudControlExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'runtime').mkdir()
        self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:100);initialize(self.a)
        self.cfg={'owner_user_id':123,'owner_private_verified':True,'owner_private_chat_id':123,'bot_username':'fixture'}
        self.policy=dict(approved=True,receiver_owner='cloud',grants_trading_permission=False,gateway_start_assistance_approved=True,
                         gateway_start_control_owner='cloud_inbox',gateway_start_control_since=50)
        self.user=patch('ops.cloud.secretary_control_executor.require_service_user');self.user.start();self.addCleanup(self.user.stop)
    def seed(self,*,uid=10,text='/login_assist',kind='GATEWAY_START_REQUESTED'):
        raw={'update_id':uid,'message':{'message_id':uid,'date':100,'from':{'id':123,'is_bot':False},'chat':{'id':123,'type':'private'},'text':text}}
        self.assertTrue(accept_update(self.a,raw,self.cfg,armed_at=1));instruction='telegram:123:'+str(uid);run=instruction+':control'
        self.a.reserve_run(run,instruction=instruction,model='PYTHON_CONTROL')
        self.a.append(run+':requested','der-secretary',origin='SYSTEM',kind=kind,parent=instruction,payload={'run':run})
        return run
    def state(self,run):
        with closing(self.a.connect()) as c:return c.execute('SELECT state FROM secretary_runs WHERE occurrence=?',(run,)).fetchone()[0]
    def test_stopped_gateway_start_is_durable_bounded_and_never_replayed(self):
        run=self.seed();calls=[]
        def invoke(argv,**kwargs):
            calls.append(argv)
            if 'show' in argv:return SimpleNamespace(returncode=0,stdout='inactive\n')
            self.assertEqual(argv,['/usr/bin/systemctl','--no-ask-password','--no-block','start','ibkr-gateway.service'])
            self.assertEqual(kwargs['timeout'],5);self.assertEqual(self.state(run),'STARTED')
            with closing(self.a.connect()) as c:self.assertTrue(c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(run+':native-start',)).fetchone())
            return SimpleNamespace(returncode=0)
        out=process_gateway_controls(self.a,self.root,self.cfg,self.policy,run_command=invoke)
        self.assertEqual(out['processed'],1);self.assertEqual(self.state(run),'SUCCEEDED')
        self.assertEqual(process_gateway_controls(self.a,self.root,self.cfg,self.policy,run_command=invoke)['processed'],0)
        self.assertEqual(len(calls),2)
    def test_active_gateway_is_never_started_or_restarted(self):
        run=self.seed();calls=[]
        def invoke(argv,**kwargs):calls.append(argv);return SimpleNamespace(returncode=0,stdout='active\n')
        out=process_gateway_controls(self.a,self.root,self.cfg,self.policy,run_command=invoke)
        self.assertEqual(out['outcomes'][0]['state'],'SUCCEEDED');self.assertEqual(len(calls),1)
        with closing(self.a.connect()) as c:self.assertIsNone(c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(run+':native-start',)).fetchone())
    def test_start_timeout_preserves_unknown_and_sends_separate_auth_notice(self):
        run=self.seed()
        def invoke(argv,**kwargs):
            if 'show' in argv:return SimpleNamespace(returncode=0,stdout='failed')
            raise subprocess.TimeoutExpired(argv,5)
        out=process_gateway_controls(self.a,self.root,self.cfg,self.policy,run_command=invoke)
        self.assertEqual(out['outcomes'][0]['state'],'UNKNOWN');self.assertEqual(self.state(run),'UNKNOWN')
        self.assertEqual(self.state(run+':outcome-notice'),'SUCCEEDED')
        with closing(self.a.connect()) as c:
            row=c.execute("SELECT payload FROM secretary_events WHERE occurrence=?",(run+':result',)).fetchone()
            self.assertEqual(json.loads(row[0])['operation_state'],'UNKNOWN')
        with patch('ops.cloud.secretary_control_executor.subprocess.run') as replay:
            process_gateway_controls(self.a,self.root,self.cfg,self.policy);replay.assert_not_called()
    def test_failed_state_observation_is_known_not_attempted_not_unknown(self):
        run=self.seed()
        with patch('ops.cloud.secretary_control_executor.subprocess.run',side_effect=subprocess.TimeoutExpired('show',3)) as transport:
            process_gateway_controls(self.a,self.root,self.cfg,self.policy)
        self.assertEqual(self.state(run),'FAILED');self.assertEqual(transport.call_count,1)
    def test_cutover_does_not_adopt_old_control_or_mac_search(self):
        run=self.seed();search=self.seed(uid=11,text='/search keyword',kind='TELEGRAM_SEARCH_REQUESTED')
        policy={**self.policy,'gateway_start_control_since':101}
        with patch('ops.cloud.secretary_control_executor.subprocess.run') as transport:
            self.assertEqual(process_gateway_controls(self.a,self.root,self.cfg,policy)['processed'],0);transport.assert_not_called()
        self.assertEqual(self.state(run),'STARTED')
        # Cloud claim filters leave the unrelated device operation untouched.
        controls=pending_controls(self.a,kinds=('GATEWAY_START_REQUESTED',),after=50,owner='cloud_inbox',limit=1)
        self.assertEqual([c['run'] for c in controls],[run])
        with closing(self.a.connect()) as c:self.assertIsNone(c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(search+':dispatch',)).fetchone())
    def test_wrong_command_or_native_owner_provenance_cannot_start(self):
        run=self.seed(text='/login_assist@other')
        with patch('ops.cloud.secretary_control_executor.subprocess.run') as transport:
            process_gateway_controls(self.a,self.root,self.cfg,self.policy);transport.assert_not_called()
        self.assertEqual(self.state(run),'FAILED')
    def test_disabled_policy_leaves_request_unclaimed(self):
        run=self.seed()
        with patch('ops.cloud.secretary_control_executor.subprocess.run') as transport:
            out=process_gateway_controls(self.a,self.root,self.cfg,{**self.policy,'gateway_start_assistance_approved':False})
        self.assertEqual(out['state'],'DISABLED');transport.assert_not_called()
        with closing(self.a.connect()) as c:self.assertIsNone(c.execute('SELECT 1 FROM secretary_events WHERE occurrence=?',(run+':dispatch',)).fetchone())
    def test_cloud_model_does_not_claim_transport_controls(self):
        from ops.cloud.secretary_rpc import dispatch
        self.seed()
        with patch('reporting.secretary_controls.pending_controls') as claim,patch('ops.cloud.secretary_rpc.reconcile_replies'),patch('ops.cloud.secretary_rpc.autonomous'),patch('ops.cloud.secretary_rpc.claim',return_value=None):
            result=dispatch(self.root,{'action':'poll'},self.cfg,{**self.policy,'model_owner':'cloud_oauth','model':'gpt-6.1-sol'},caller='cloud_oauth')
        claim.assert_not_called();self.assertEqual(result['controls'],[])
    def test_mac_claim_excludes_cloud_owned_gateway(self):
        from ops.cloud.secretary_rpc import dispatch
        with patch('reporting.secretary_controls.pending_controls',return_value=[]) as claim,patch('ops.cloud.secretary_rpc.reconcile_replies'):
            dispatch(self.root,{'action':'poll'},self.cfg,{**self.policy,'model_owner':'cloud_oauth'},caller='mac_bridge')
        self.assertEqual(claim.call_args.kwargs['kinds'],('TELEGRAM_SEARCH_REQUESTED',))
