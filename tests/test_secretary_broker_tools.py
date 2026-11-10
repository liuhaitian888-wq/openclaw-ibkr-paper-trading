from contextlib import closing
import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_broker import submit,result
from trading.secretary_broker_owner import SecretaryBrokerOwner
from trading.paper_safety_monitor import ACCOUNT
from reporting.secretary_operations import cloud_task,service_status


class BrokerToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=100.
        self.archive=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:self.now)
        self.monitor=SimpleNamespace(lock=threading.RLock(),clock=lambda:self.now,
            state=dict(reconciled_at=90,last_server_reply=100,positions={'AAPL':2},orders={},executions={},quotes={'AAPL':{'bid':10,'ask':11,'data_type':1,'bid_at':100,'ask_at':100}}))
        self.ready=True;self.monitor._complete=lambda:self.ready
        self.calls=[]
        def reconcile():self.calls.append('reconcile');self.ready=False
        self.client=SimpleNamespace(monitor=self.monitor,connection_generation='g1',accounts=[ACCOUNT],
            isConnected=lambda:True,reconcile=reconcile,reqCurrentTime=lambda:self.calls.append('clock'),
            reqAccountSummary=lambda *x:self.calls.append(('summary',x)),cancelAccountSummary=lambda n:self.calls.append(('cancel',n)))
        self.owner=SecretaryBrokerOwner(self.client,self.archive);self.addCleanup(self.owner.close)
    def queue(self,area='positions',step=1):
        return submit(self.archive,{'name':'broker_query','area':area},run='r',step=step,wait_seconds=0)
    def complete(self):
        self.now+=1;self.ready=True;self.monitor.state.update(reconciled_at=self.now,last_server_reply=self.now)
        self.owner.poll()
    def test_existing_owner_executes_current_query_and_duplicate_never_replays(self):
        q=self.queue();self.assertTrue(self.owner.poll());self.assertEqual(self.calls,['reconcile','clock'])
        self.complete();r=result(self.archive,q['id']);self.assertEqual(r['state'],'SUCCEEDED')
        self.assertEqual(r['result']['data']['positions'],{'AAPL':2})
        self.assertEqual(r['result']['source'],'OWNED_LIVE_BROKER_QUERY')
        self.queue();self.owner.poll();self.assertEqual(self.calls,['reconcile','clock'])
    def test_current_completion_required_and_reconnect_fails_closed(self):
        q=self.queue();self.owner.poll();self.owner.poll()
        self.assertEqual(result(self.archive,q['id'])['state'],'STARTED')
        self.client.connection_generation='g2';self.owner.poll()
        self.assertEqual(result(self.archive,q['id'])['state'],'UNAVAILABLE')
    def test_cash_summary_end_and_account_are_verified_subscription_is_cancelled(self):
        q=self.queue('cash');self.owner.poll();n=self.owner.pending['request_id']
        self.owner.summary(n,ACCOUNT,'CashBalance','12.00','EUR');self.complete()
        self.assertEqual(result(self.archive,q['id'])['state'],'STARTED')
        self.owner.summary_end(n);self.owner.poll()
        self.assertEqual(result(self.archive,q['id'])['state'],'SUCCEEDED');self.assertIn(('cancel',n),self.calls)
    def test_documented_all_ledger_retains_native_identity_only_for_single_managed_account(self):
        q=self.queue('cash');self.owner.poll();n=self.owner.pending['request_id']
        self.owner.summary(n,ACCOUNT,'AccountType','INDIVIDUAL','')
        self.owner.summary(n,'All','CashBalance','12.00','EUR')
        self.owner.summary(n,'All','NetLiquidation','999','USD')
        self.owner.summary_end(n);self.complete()
        rows=result(self.archive,q['id'])['result']['data']['account_summary']
        aggregate=[x for x in rows if x['account']=='All']
        self.assertEqual(len(aggregate),1);self.assertEqual(aggregate[0]['scope'],'ALL_MANAGED_ACCOUNTS_SINGLE_ACCOUNT_VERIFIED')
        self.assertEqual(aggregate[0]['tag'],'CashBalance')
        q=self.queue('cash',step=2);self.owner.poll();n=self.owner.pending['request_id']
        self.client.accounts=[ACCOUNT,'OTHER'];self.owner.summary(n,'All','CashBalance','12','EUR');self.owner.poll()
        self.assertEqual(result(self.archive,q['id'])['state'],'UNAVAILABLE')

    def test_cross_account_and_timeout_cancel_only_owned_request(self):
        q=self.queue('account');self.owner.poll();n=self.owner.pending['request_id']
        self.owner.summary(n,'OTHER','NetLiquidation','100','USD');self.owner.poll()
        self.assertEqual(result(self.archive,q['id'])['state'],'UNAVAILABLE');self.assertIn(('cancel',n),self.calls)
        self.ready=True;q=self.queue('account',step=2);self.owner.poll();n=self.owner.pending['request_id']
        self.now+=21;self.owner.poll();self.assertEqual(result(self.archive,q['id'])['state'],'UNAVAILABLE');self.assertIn(('cancel',n),self.calls)
    def test_stale_queue_and_changed_content_are_not_executed(self):
        q=self.queue();self.now+=31;self.owner.poll();self.assertEqual(self.calls,[])
        self.assertEqual(result(self.archive,q['id'])['state'],'UNAVAILABLE')
        with self.assertRaises(ValueError):self.queue('orders')
    def test_previous_started_attempt_survives_new_owner_without_replay(self):
        q=self.queue();self.owner.poll();new=SecretaryBrokerOwner(self.client,self.archive)
        self.assertEqual(result(self.archive,q['id'])['state'],'UNKNOWN');new.poll()
        self.assertEqual(self.calls,['reconcile','clock']);new.close()
    def test_quote_projection_does_not_mutate_monitor_and_reports_stale(self):
        q=self.queue('quotes');self.owner.poll();before=copy.deepcopy(self.monitor.state['quotes'])
        self.now+=10;self.complete();r=result(self.archive,q['id'])
        self.assertEqual(r['result']['data']['quotes']['AAPL']['freshness'],'STALE_OR_UNENTITLED')
        self.assertEqual(self.monitor.state['quotes'],before)
    def test_selected_snapshot_uses_one_reconciliation_and_returns_only_requested_data(self):
        q=submit(self.archive,{'name':'broker_query','area':'snapshot','sections':['cash','positions','orders']},run='r',step=1,wait_seconds=0)
        self.owner.poll();n=self.owner.pending['request_id']
        self.owner.summary(n,ACCOUNT,'TotalCashValue','12','EUR');self.owner.summary_end(n);self.complete()
        data=result(self.archive,q['id'])['result']['data']
        self.assertEqual(set(data),{'positions','orders','account_summary'})
        self.assertEqual(self.calls.count('reconcile'),1)
        self.assertEqual(len([x for x in self.calls if isinstance(x,tuple) and x[0]=='summary']),1)
    def test_selected_positions_snapshot_does_not_open_account_subscription(self):
        q=submit(self.archive,{'name':'broker_query','area':'snapshot','sections':['positions','orders']},run='r',step=1,wait_seconds=0)
        self.owner.poll();self.complete()
        self.assertEqual(set(result(self.archive,q['id'])['result']['data']),{'positions','orders'})
        self.assertFalse(any(isinstance(x,tuple) and x[0]=='summary' for x in self.calls))
    def test_invalid_snapshot_sections_do_not_create_requests(self):
        for area,sections in [('positions',['orders']),('snapshot',[]),('snapshot',['orders','orders']),('snapshot',['shell']),('snapshot',[[1]])]:
            with self.subTest(area=area,sections=sections),self.assertRaises(ValueError):
                submit(self.archive,{'name':'broker_query','area':area,'sections':sections},run='r',step=1,wait_seconds=0)

    def test_invalid_query_and_symbol_limit_do_not_enqueue(self):
        for request in ({'name':'broker_query','area':'placeOrder'}, {'name':'broker_query','area':'quotes','symbols':['X']*6}, {'name':'broker_query','area':'orders','command':'anything'}):
            with self.assertRaises(ValueError):submit(self.archive,request,run='r',step=1,wait_seconds=0)


class OperationsToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.archive=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:100.)
        self.archive.append('q','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'修复并测试日志工具'})
        self.policy={'engineering_cloud_approved':True,'cloud_environment_id':'asenv_fixture123','cloud_branch':'main'}
        self.auth=patch('reporting.secretary_oauth.oauth_ready',return_value=True);self.auth.start();self.addCleanup(self.auth.stop)
    def cloud(self,request=None):
        return cloud_task(self.archive,self.root,request or {'name':'cloud_task_submit','plan':'修复日志'},self.policy,run='r',step=1,instruction='q')
    def test_cloud_submission_receipt_preserves_owner_and_never_applies_or_replays(self):
        with patch('reporting.secretary_operations.command',return_value='https://chatgpt.com/codex/tasks/task_fixture123456') as call:
            r=self.cloud();again=self.cloud()
        self.assertEqual(r['state'],'SUBMITTED');self.assertEqual(again['task_id'],r['task_id']);self.assertEqual(call.call_count,1)
        argv=call.call_args.args[0];self.assertIn('--attempts',argv);self.assertIn('修复并测试日志工具',argv[-1]);self.assertIn('untrusted planning data',argv[-1])
        self.assertFalse(r['receipt']['automatic_apply_or_deploy'])
    def test_unknown_submission_never_retries(self):
        with patch('reporting.secretary_operations.command',side_effect=TimeoutError) as call:
            self.assertEqual(self.cloud()['state'],'UNKNOWN');self.assertEqual(self.cloud()['state'],'UNKNOWN')
        self.assertEqual(call.call_count,1)
    def test_autonomous_cannot_submit_and_other_task_id_not_accessible(self):
        self.archive.append('auto','der-secretary',origin='SYSTEM',kind='AUTONOMOUS_INSTRUCTION',payload={'text':'inspect'})
        with self.assertRaises(PermissionError):cloud_task(self.archive,self.root,{'name':'cloud_task_submit','plan':'go'},self.policy,run='auto',step=1,instruction='auto')
        with self.assertRaises(PermissionError):self.cloud({'name':'cloud_task_status','task_id':'task_notours123456'})
    def test_service_inspection_has_fixed_argv_no_shell(self):
        with patch('reporting.secretary_operations.command',return_value='Id=ibkr-gateway.service\nActiveState=active\n') as call:
            r=service_status({'services':['gateway']})
        self.assertFalse(r['mutated']);self.assertEqual(call.call_args.args[0][2],'ibkr-gateway.service')
        with self.assertRaises(ValueError):service_status({'services':['gateway;echo injected']})
    def test_cloud_environment_cannot_be_model_selected(self):
        self.policy['cloud_environment_id']='bad;env'
        with self.assertRaises(ValueError):self.cloud()


class DispatcherToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.archive=SecretaryArchive(self.root/'agent_secretary.sqlite3')
        from reporting.secretary_queue import initialize
        initialize(self.archive)
        self.archive.append('q','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'查我的实时持仓','chat_id':123})
        self.archive.reserve_run('r',instruction='q',model='gpt-6.1-sol')
    def test_dispatch_calls_python_once_and_archived_broker_result_routes_private(self):
        from ops.cloud.secretary_rpc import dispatch
        from reporting.incidents import IncidentStore
        (self.root/'runtime').mkdir();store=IncidentStore(self.root/'runtime/recovery.sqlite3')
        req={'action':'tool','run':'r','step':1,'request':{'name':'broker_query','area':'positions'},'response_mode':'TASK'}
        with patch('reporting.secretary_operations.service_status',return_value={'services':[{'properties':{'ActiveState':'active'}}]}),patch('reporting.secretary_broker.submit',return_value={'state':'SUCCEEDED','source':'OWNED_LIVE_BROKER_QUERY'}) as submit_tool:
            first=dispatch(self.root,req,{},dict(broker_queries_approved=True))
            self.assertEqual(dispatch(self.root,req,{},dict(broker_queries_approved=True)),first)
        self.assertEqual(submit_tool.call_count,1)
        dispatch(self.root,{'action':'finish','run':'r','state':'SUCCEEDED','result':{'summary':'持仓已核验','response_mode':'TASK'}},{},{})
        with closing(store.connect()) as c:
            payload=json.loads(c.execute("SELECT payload FROM notification_outbox WHERE incident_key='secretary:r'").fetchone()[0])
        self.assertTrue(payload['requires_response']);self.assertEqual(payload['sensitivity'],'PRIVATE_ACCOUNT_OPERATIONS')
    def test_all_registered_db_paths_are_explicit_and_missing_not_created(self):
        from reporting.secretary_read import tool,REGISTRY
        data=tool(self.root,{'name':'databases'})
        self.assertEqual({x['query_database_id'] for x in data['databases']},set(REGISTRY))
        for row in data['databases']:
            self.assertEqual(row['absolute_path'],str(self.root/row['path']))
        self.assertFalse((self.root/'financial_ledger.sqlite3').exists())

    def test_stopped_broker_owner_returns_immediately_without_queue_or_start(self):
        from ops.cloud.secretary_rpc import dispatch
        req={'action':'tool','run':'r','step':1,'request':{'name':'broker_query','area':'positions'},'response_mode':'CHAT'}
        with patch('reporting.secretary_operations.service_status',return_value={'services':[{'properties':{'ActiveState':'inactive'}}]}),patch('reporting.secretary_broker.submit') as queue:
            r=dispatch(self.root,req,{},dict(broker_queries_approved=True))
        self.assertEqual(r['state'],'BROKER_OWNER_INACTIVE');queue.assert_not_called()
