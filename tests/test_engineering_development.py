from contextlib import closing
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reporting.agent_secretary import SecretaryArchive
from reporting.engineering_development import approved, tool, run_once, CLASS
from reporting.engineering_patch import apply, FILES, GUARD
from reporting.engineering_relay import propose
from reporting.engineering_tasks import initialize
from reporting.incidents import IncidentStore
from reporting.secretary_queue import claim as research_claim, initialize as inbox_initialize


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=1000
        self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:self.now)
        initialize(self.a);inbox_initialize(self.a);IncidentStore(self.root/'runtime/recovery.sqlite3')
        self.source=Path(__file__).resolve().parents[1]
        head=subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=self.source,text=True).strip()
        self.value={'approved':True,'model_owner':'cloud_oauth','model_owner_since':900,'grants_trading_permission':False,
            'engineering_development_scope':{'approved':True,'class':CLASS,'max_tasks':1,'version':'dev-once',
                'base_commit':head,'since':900,'expires':2000,'grants_trading_permission':False,
                'grants_deployment_permission':False,'authority':{'kind':'CODEX_HUMAN_AUTHORIZATION',
                    'thread_id':'01a1c855-b112-7351-a5b1-0f9173f49ea5','message_id':'01a1c85c-9911-7cf0-a5f2-8c8840382068'}}}
        self.a.append('request','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'check engineering'})
        self.a.reserve_run('secretary-run',instruction='request',model='gpt-6.1-sol')
        self.proposal=propose(self.a,{'title':'Policy types','observation':'A malformed timestamp yields TypeError',
            'suggested_change':'Validate types first','evidence':['approved-source:policy']},instruction='request')['id']
        self.calls=0
        self.patchers=[patch('reporting.engineering_development.SecretaryArchive',return_value=self.a),
                       patch('reporting.engineering_sandbox.capabilities',return_value=(None,None,4)),
                       patch('reporting.engineering_development.check_source',return_value=self.source)]
        for p in self.patchers:p.start();self.addCleanup(p.stop)

    def enqueue(self):
        return tool(self.a,self.root,{'name':'engineering_development_submit','proposal_id':self.proposal},
            self.value,instruction='request',run='secretary-run')

    def backend(self, context, *, record, **kwargs):
        self.calls+=1
        record('THREAD_CREATED',{'thread_id':'thread'})
        record('TURN_ACCEPTED',{'thread_id':'thread','turn_id':'turn'})
        name=FILES[0];src=context['source']['files'][name]
        content=src['content'].replace("    scope = value.get('engineering_scope', {})\n", "    scope = value.get('engineering_scope', {})\n"+GUARD,1)
        result={'thread_id':'thread','turn_id':'turn','status':'completed','summary':'Scoped correction.',
            'edits':[{'path':name,'before_sha256':src['sha256'],'content':content}]}
        record('TURN_COMPLETED',result);return result

    def runner(self, location, mode, **kwargs):
        if mode=='canary':return {'exit_code':0,'stdout':json.dumps({'passed':True}),'stderr':''}
        if mode=='regression' and not (location/'patch.diff').exists():
            return {'exit_code':1,'stdout':json.dumps({'regression':CLASS,'cases':7,'failures':['TypeError']}),'stderr':''}
        return {'exit_code':0,'stdout':'passed','stderr':''}

    def execute(self, backend=None, tester=None):
        return run_once(self.root,self.value,home=self.root/'oauth',backend=backend or self.backend,tester=tester or self.runner)

    def test_model_proposal_keeps_provenance_and_cannot_claim_user_native_authority(self):
        item=self.enqueue();self.assertEqual('QUEUED_NOT_NATIVE_ACCEPTED',item['state'])
        with closing(self.a.connect()) as c:
            p=c.execute('SELECT origin FROM secretary_events WHERE occurrence=?',(self.proposal,)).fetchone()
            row=c.execute('SELECT instruction,payload FROM secretary_engineering_tasks').fetchone()
            ins=c.execute('SELECT origin,kind,parent FROM secretary_events WHERE occurrence=?',(row[0],)).fetchone()
            auth=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(ins[2],)).fetchone()
        self.assertEqual(('MODEL',),p);self.assertEqual(('SYSTEM','ENGINEERING_INSTRUCTION'),ins[:2])
        self.assertTrue(json.loads(auth[0])['not_a_native_telegram_message'])
        self.assertIsNone(research_claim(self.a,model='gpt-6.1-sol',now=self.now))

    def test_unapproved_class_foreign_proposal_stale_run_or_changed_owner_scope_rejected(self):
        bad=json.loads(json.dumps(self.value));bad['engineering_development_scope']['class']='arbitrary-shell'
        with self.assertRaises(PermissionError):approved(bad,self.now)
        with self.assertRaises(PermissionError):
            tool(self.a,self.root,{'name':'engineering_development_submit','proposal_id':'engineering-proposal:'+'f'*24},
                 self.value,instruction='request',run='secretary-run')
        self.now=2100
        with self.assertRaises(PermissionError):self.enqueue()

    def test_two_tool_rounds_can_create_real_model_proposal_and_queue_under_separate_authority(self):
        result=tool(self.a,self.root,{'name':'engineering_development_submit','proposal':{
            'title':'Bounded malformed policy defect','observation':'Type comparison precedes validation',
            'suggested_change':'Only insert class guards','evidence':['approved-source:sha']}},self.value,
            instruction='request',run='secretary-run')
        with closing(self.a.connect()) as c:
            payload=json.loads(c.execute('SELECT payload FROM secretary_engineering_tasks WHERE id=?',(result['task_id'],)).fetchone()[0])
            self.assertEqual(('MODEL','ENGINEERING_PROPOSAL'),c.execute('SELECT origin,kind FROM secretary_events WHERE occurrence=?',(payload['proposal_id'],)).fetchone())
        self.assertEqual('QUEUED_NOT_NATIVE_ACCEPTED',result['state'])

    def test_real_git_isolated_worktree_patch_artifact_budget_and_private_result(self):
        item=self.enqueue();self.assertEqual(item['task_id'],self.enqueue()['task_id'])
        self.a.finish_run('secretary-run',state='FAILED')
        self.assertEqual('PATCH_READY',self.execute());self.assertEqual(1,self.calls)
        self.assertEqual('IDLE',self.execute());self.assertEqual(1,self.calls)
        folder=self.root/'engineering/development'/item['task_id'].split(':')[1]
        self.assertTrue((folder/'worktree/.git').is_file())
        self.assertTrue((folder/'canary-sentinel').is_file())
        self.assertTrue((folder/'patch.diff').is_file())
        self.assertNotIn(GUARD,(self.source/FILES[0]).read_text())
        report=json.loads((folder/'result.json').read_text())
        self.assertEqual(report['patch']['patch_sha256'],hashlib.sha256((folder/'patch.diff').read_bytes()).hexdigest())
        with closing(self.a.connect()) as c:
            self.assertEqual(2,c.execute("SELECT count(*) FROM secretary_runs WHERE model='gpt-6.1-sol'").fetchone()[0])
        store=IncidentStore(self.root/'runtime/recovery.sqlite3')
        with closing(store.connect()) as c:
            rows=c.execute("SELECT payload FROM notification_outbox WHERE incident_key LIKE '%:RESULT'").fetchall()
        self.assertEqual(1,len(rows));self.assertTrue(json.loads(rows[0][0])['requires_response'])

    def test_native_timeout_preserves_unknown_and_never_regenerates_patch(self):
        self.enqueue();self.a.finish_run('secretary-run',state='FAILED')
        def uncertain(*args,**kwargs):self.calls+=1;raise TimeoutError()
        self.assertEqual('UNKNOWN',self.execute(backend=uncertain));self.assertEqual('IDLE',self.execute())
        self.assertEqual(1,self.calls)

    def test_kernel_canary_failure_prevents_model_and_untrusted_tests(self):
        self.enqueue();self.a.finish_run('secretary-run',state='FAILED');modes=[]
        def bad(location,mode,**kwargs):modes.append(mode);return {'exit_code':1,'stdout':'{}','stderr':''}
        self.assertEqual('UNKNOWN',self.execute(tester=bad));self.assertEqual(['canary'],modes);self.assertEqual(0,self.calls)

    def test_patch_cannot_escape_files_change_base_or_modify_test_entry(self):
        job=self.root/'isolated';work=job/'worktree';(work/'reporting').mkdir(parents=True)
        file=work/FILES[0];file.write_text('x=1\n');before=hashlib.sha256(file.read_bytes()).hexdigest()
        for path,base in [('../secret',before),('scripts/run_worktree_tests.py',before),(FILES[0],'f'*64)]:
            with self.assertRaises((PermissionError,ValueError)):
                apply(job,{'edits':[{'path':path,'before_sha256':base,'content':'x=2\n'}]})
            self.assertEqual('x=1\n',file.read_text())

    def test_semantic_guard_rejects_model_test_forgery_or_permission_weakening(self):
        job=self.root/'guarded';work=job/'worktree';(work/'reporting').mkdir(parents=True)
        file=work/FILES[0];original=(self.source/FILES[0]).read_text();file.write_text(original)
        before=hashlib.sha256(file.read_bytes()).hexdigest()
        for content in (original+'\nraise SystemExit(0)\n',original.replace("scope.get('approved') is not True","False")):
            with self.assertRaises(PermissionError):
                apply(job,{'edits':[{'path':FILES[0],'before_sha256':before,'content':content}]})
            self.assertEqual(original,file.read_text())

    def test_public_result_projection_failure_never_repeats_patch_or_tests(self):
        self.enqueue();self.a.finish_run('secretary-run',state='FAILED')
        with patch('reporting.engineering_development.finish',side_effect=OSError()):
            self.assertEqual('COMPLETION_RECONCILIATION_REQUIRED',self.execute())
        self.assertEqual('COMPLETION_RECONCILED',self.execute());self.assertEqual(1,self.calls)
