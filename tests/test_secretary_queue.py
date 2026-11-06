from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize,accept_update,cursor,autonomous,claim,enqueue_reply,AUTHORITY,CONVERSATION
from reporting.incidents import IncidentStore
from reporting.notification_text import notification_text

class SecretaryQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.a=SecretaryArchive(self.root/'agent.sqlite3',clock=lambda:100000)
        initialize(self.a);self.config={'chat_id':-100,'owner_user_id':123}
    def update(self,**changes):
        m={'chat':{'id':-100},'from':{'id':123,'is_bot':False},'text':'research data quality','date':100000,'message_id':1};m.update(changes)
        return {'update_id':1,'message':m}
    def test_only_owner_native_recent_messages_are_accepted(self):
        variants=[{'from':{'id':124,'is_bot':False}},{'from':{'id':123,'is_bot':True}},
                  {'sender_chat':{'id':-100}},{'forward_origin':{'type':'user'}},{'date':99999},{'chat':{'id':-200}}]
        for v in variants:self.assertFalse(accept_update(self.a,self.update(**v),self.config,armed_at=100000))
        self.assertTrue(accept_update(self.a,self.update(),self.config,armed_at=100000))
        self.assertTrue(accept_update(self.a,self.update(),self.config,armed_at=100000))
        self.assertEqual(len(self.a.history(CONVERSATION)),2);self.assertEqual(cursor(self.a),2)
    def test_paid_run_is_reserved_once_and_unknown_survives_restart(self):
        accept_update(self.a,self.update(),self.config,armed_at=100000)
        job=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.assertIsNotNone(job);self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=100000))
        self.a.finish_run(job['run'],state='UNKNOWN')
        reloaded=SecretaryArchive(self.a.path,clock=lambda:100000)
        self.assertIsNone(claim(reloaded,model='gpt-6.1-sol',now=100000))
        self.assertFalse(autonomous(reloaded,now=200000))
    def test_autonomous_instruction_has_user_authority_and_slot_dedup(self):
        self.assertTrue(autonomous(self.a,now=100000));self.assertFalse(autonomous(self.a,now=100001))
        job=claim(self.a,model='gpt-6.1-sol',now=100000);self.assertIsNotNone(job)
        self.a.append('forged',CONVERSATION,origin='SYSTEM',kind='AUTONOMOUS_INSTRUCTION',payload={})
        with self.assertRaises(ValueError):self.a.reserve_run('forged-run',instruction='forged',model='gpt-6.1-sol')
    def test_success_archive_and_outbox_are_idempotent_and_not_an_incident(self):
        autonomous(self.a,now=100000);job=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.a.append('result',CONVERSATION,origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',parent=job['instruction'],payload={'summary':'tested'})
        self.a.finish_run(job['run'],state='SUCCEEDED',result_event='result')
        store=IncidentStore(self.root/'recovery.sqlite3')
        enqueue_reply(self.a,store,job['run'],'tested');enqueue_reply(self.a,store,job['run'],'tested')
        item=store.claim();self.assertEqual(item['kind'],'SECRETARY_REPLY');self.assertIsNone(store.claim())
        text=notification_text(item,100000);self.assertIn('研究秘书',text);self.assertNotIn('故障批次',text)
        with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM incidents').fetchone()[0],0)
    def test_reconciles_crash_between_archive_success_and_outbox_enqueue(self):
        from reporting.secretary_queue import reconcile_replies
        autonomous(self.a,now=100000);job=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.a.append('result',CONVERSATION,origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',parent=job['instruction'],payload={'summary':'actual result'})
        self.a.finish_run(job['run'],state='SUCCEEDED',result_event='result')
        store=IncidentStore(self.root/'recovery.sqlite3')
        reconcile_replies(self.a,store);reconcile_replies(self.a,store)
        item=store.claim();self.assertEqual(item['payload']['reason'],'actual result');self.assertIsNone(store.claim())
    def test_daily_budget_counts_started_jobs_not_just_successes(self):
        for i in range(25):
            self.a.append('owner:'+str(i),CONVERSATION,origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'fixture'})
        for _ in range(24):self.assertIsNotNone(claim(self.a,model='gpt-6.1-sol',now=100000))
        self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=100000))
