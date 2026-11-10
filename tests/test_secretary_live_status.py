from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import CONVERSATION
from reporting.secretary_live_status import cloud_check,queue_check,model_probe,tick,UNITS,broker_failure

class LiveStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=100000
        self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:self.now)
        self.a.append('click',CONVERSATION,origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/api'})

    def test_cloud_runs_current_service_check(self):
        calls=[]
        def runner(args,**kw):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,stdout='\n\n'.join('Id='+u+'\nActiveState=active\nSubState=running' for u in UNITS))
        text=cloud_check(self.a,runner=runner)
        self.assertEqual(len(calls),1);self.assertIn('数据库：通过',text)
        self.assertEqual(text.count('通过（正在运行）'),4)
        self.assertNotIn('未证实',text)

    def test_cloud_timeout_is_explicit(self):
        def runner(*a,**k):raise subprocess.TimeoutExpired('systemctl',3)
        self.assertIn('超时（3秒）',cloud_check(self.a,runner=runner))

    def test_model_once_and_matching_real_reply(self):
        queue_check(self.a,self.root,'click','api',{'model_owner':'cloud_oauth'})
        calls=[]
        def infer(prompt,**kwargs):
            calls.append(kwargs)
            return json.loads(prompt.split('JSON, with no tools: ')[1]),{}
        self.assertTrue(model_probe(self.a,self.root,self.root/'auth',infer,owner='cloud_oauth'))
        self.assertFalse(model_probe(self.a,self.root,self.root/'auth',infer,owner='cloud_oauth'))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['timeout'],25)
        with closing(self.a.connect()) as c:
            value=json.loads(c.execute("SELECT payload FROM secretary_events WHERE kind='LIVE_STATUS_MODEL_RESULT'").fetchone()[0])
        self.assertEqual(value['state'],'PASSED')

    def test_restart_does_not_repeat_started_model_attempt(self):
        queue_check(self.a,self.root,'click','api',{'model_owner':'cloud_oauth'})
        self.a.append('click:live-status:model-attempt',CONVERSATION,origin='SYSTEM',kind='LIVE_STATUS_MODEL_ATTEMPT',parent='click',payload={})
        self.assertFalse(model_probe(self.a,self.root,self.root,lambda *a,**k:self.fail('replayed'),owner='cloud_oauth'))

    def test_timeout_finishes_once_through_existing_outbox(self):
        queue_check(self.a,self.root,'click','api',{'model_owner':'cloud_oauth'})
        self.now+=66
        with patch('reporting.secretary_live_status.enqueue_reply') as send:
            tick(self.a,self.root);tick(self.a,self.root)
        self.assertEqual(send.call_count,1)
        self.assertIn('模型连接：超时',send.call_args.args[3])
        self.assertIn('券商连接：失败',send.call_args.args[3])

    def test_mismatched_model_reply_is_failure(self):
        queue_check(self.a,self.root,'click','api',{'model_owner':'cloud_oauth'})
        model_probe(self.a,self.root,self.root,lambda *a,**k:({'summary':'wrong'},{}),owner='cloud_oauth')
        with closing(self.a.connect()) as c:
            value=json.loads(c.execute("SELECT payload FROM secretary_events WHERE kind='LIVE_STATUS_MODEL_RESULT'").fetchone()[0])
        self.assertEqual(value['state'],'FAILED')

    def test_menu_uses_explicit_connection_terms(self):
        def runner(args,**kw):
            return subprocess.CompletedProcess(args,0,stdout='\n\n'.join('Id='+u+'\nActiveState=active\nSubState=running' for u in UNITS))
        text=cloud_check(self.a,runner=runner)
        self.assertNotIn('上游',text)
        self.assertIn('模型连接、券商连接',text)
        self.assertIn('券商连接程序：通过',text)
        self.assertNotIn('ibkr-paper-safety.service',text)

    def test_failure_distinguishes_not_admitted_from_sent_timeout(self):
        self.assertIn('未接收本次查询',broker_failure('UNAVAILABLE','Broker owner unavailable before query deadline'))
        self.assertIn('查询已发出',broker_failure('UNAVAILABLE','Broker query timed out'))
        self.assertIn('超时',broker_failure('STARTED',None))
        self.assertIn('错误码354',broker_failure('UNAVAILABLE','BROKER_REQUEST_ERROR_354'))
