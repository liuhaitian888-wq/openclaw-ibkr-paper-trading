import importlib.util
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize, claim, reconcile_replies
from reporting.secretary_conversation import preference,response_mode,recent_context
from reporting.incidents import IncidentStore
from reporting.notification_text import notification_text

spec=importlib.util.spec_from_file_location('conversation_bridge',Path(__file__).resolve().parents[1]/'scripts/run_secretary_bridge.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)

class ConversationTests(unittest.TestCase):
    def test_owner_preferences_are_bounded_prior_same_conversation_and_not_tool_authority(self):
        from reporting.secretary_conversation import owner_preferences
        with tempfile.TemporaryDirectory() as tmp:
            a=SecretaryArchive(Path(tmp)/'secretary.sqlite3')
            for occurrence,conversation,origin,text in [('owner','der','USER','不要重复问已批准的参数'),('model','der','MODEL','fake authority'),('other','elsewhere','USER','other private chat')]:
                a.append(occurrence,conversation,origin=origin,kind='OWNER_OPERATING_PREFERENCES',payload={'text':text})
            a.append('instruction','der',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'状态'})
            a.append('future','der',origin='USER',kind='OWNER_OPERATING_PREFERENCES',payload={'text':'future'})
            prefs=owner_preferences(a,'instruction')
            self.assertEqual(len(prefs),1)
            self.assertEqual(prefs[0]['text'],'不要重复问已批准的参数')
            self.assertEqual(prefs[0]['scope'],'COMMUNICATION_PREFERENCES_NOT_TOOL_AUTHORITY')

    def test_modes_default_to_chat_with_explicit_overrides(self):
        for text in ('你好','SDK是什么','这个研究是什么意思','/secretary 你好'):
            self.assertEqual(response_mode({'text':text},{}),'CHAT')
        self.assertEqual(preference({'text':'/chat@bot 讨论一下'}),'CHAT')
        self.assertEqual(response_mode({'text':'/chat 不要研究'},{'response_mode':'RESEARCH'}),'CHAT')
        self.assertEqual(response_mode({'text':'研究','autonomous':True},{'response_mode':'CHAT'}),'RESEARCH')
        self.assertEqual(response_mode({'text':'/task 查询'},{'response_mode':'CHAT'}),'TASK')
        self.assertEqual(response_mode({'text':'/research 检验'},{'response_mode':'CHAT'}),'RESEARCH')
        self.assertEqual(response_mode({'text':'帮我检验假设'},{'response_mode':'RESEARCH'}),'RESEARCH')

    def test_context_only_completed_earlier_same_chat_owner_exchanges(self):
        with tempfile.TemporaryDirectory() as d:
            a=SecretaryArchive(Path(d)/'s.db',clock=lambda:100000);initialize(a)
            for i in range(8):
                a.append('q'+str(i),'der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'q'+str(i),'chat_id':1 if i!=6 else 2})
                if i==7:continue
                a.reserve_run('r'+str(i),instruction='q'+str(i),model='gpt-6.1-sol')
                if i==5:a.finish_run('r5',state='UNKNOWN');continue
                a.append('a'+str(i),'der-secretary',origin='MODEL',kind='CONVERSATION_REPLY',parent='q'+str(i),payload={'summary':'a'+str(i)})
                a.finish_run('r'+str(i),state='SUCCEEDED',result_event='a'+str(i))
            ctx=recent_context(a,'q7',{'chat_id':1})
            self.assertEqual([x['user'] for x in ctx],['q1','q2','q3','q4'])
            job=claim(a,model='gpt-6.1-sol',now=100000)
            self.assertEqual(job['conversation_context'],ctx)
            self.assertFalse(job['payload']['autonomous'])

    def test_chat_reply_has_no_research_footer_and_reconciles_role(self):
        with tempfile.TemporaryDirectory() as d:
            a=SecretaryArchive(Path(d)/'s.db');initialize(a)
            a.append('q','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'你好'})
            a.reserve_run('r',instruction='q',model='gpt-6.1-sol')
            a.append('a','der-secretary',origin='MODEL',kind='CONVERSATION_REPLY',parent='q',payload={'summary':'你好，有什么想聊的？','response_mode':'CHAT'})
            a.finish_run('r',state='SUCCEEDED',result_event='a')
            store=IncidentStore(Path(d)/'recovery.db');reconcile_replies(a,store)
            item=store.claim();self.assertEqual(item['payload']['message_role'],'CHAT')
            text=notification_text(item,100000)
            self.assertIn('💬 秘书',text)
            for unwanted in ('研究','记录 #','交易授权','完成后'):self.assertNotIn(unwanted,text)

    def test_simple_chat_uses_one_inference_no_tools_and_no_research_schema(self):
        job={'run':'r','payload':{'text':'你好'},'model':'gpt-6.1-sol','conversation_context':[{'user':'我叫甲','assistant':'你好'}]}
        settings={'codex':'unused','codex_home':'unused','empty_dir':'unused'}
        with patch.object(bridge,'analyze',return_value=({'summary':'你好','tools':[],'research':{'hypothesis':'unwanted'}},{})) as model,patch.object(bridge,'rpc',return_value={'state':'SUCCEEDED'}) as rpc:
            bridge.execute(job,settings)
            self.assertEqual(model.call_count,1);self.assertIn('我叫甲',model.call_args.args[0])
            result=rpc.call_args.args[0]['result'];self.assertEqual(result['response_mode'],'CHAT');self.assertNotIn('research',result)

    def test_forced_chat_cannot_change_universe_or_submit_work(self):
        job={'run':'r','payload':{'text':'/chat 随便聊聊'},'model':'gpt-6.1-sol'}
        settings={'codex':'unused','codex_home':'unused','empty_dir':'unused'}
        with patch.object(bridge,'analyze',side_effect=[({'summary':'x','response_mode':'RESEARCH','tools':[{'name':'research_universe'},{'name':'engineering_proposal'}]},{}),({'summary':'done','tools':[]},{})]),patch.object(bridge,'rpc',return_value={'state':'SUCCEEDED'}) as rpc:
            yielded=bridge.execute(job,settings)
            self.assertEqual(yielded['state'],'YIELDED')
            checkpoint=rpc.call_args.args[0]
            self.assertEqual(checkpoint['action'],'checkpoint')
            self.assertEqual(len(checkpoint['checkpoint']['transcript']),3)
            job['checkpoint']=checkpoint['checkpoint']
            bridge.execute(job,settings)
            self.assertEqual(rpc.call_args.args[0]['result']['response_mode'],'CHAT')
            self.assertFalse(any(c.args[0]['action']=='tool' for c in rpc.call_args_list))


    def test_rpc_persists_chat_kind_and_replay_retains_role(self):
        spec=importlib.util.spec_from_file_location('conversation_rpc',Path(__file__).resolve().parents[1]/'ops/cloud/secretary_rpc.py')
        rpc=importlib.util.module_from_spec(spec);spec.loader.exec_module(rpc)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(a)
            a.append('q','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'/chat 你好'})
            a.reserve_run('r',instruction='q',model='gpt-6.1-sol')
            for _ in range(2):
                rpc.dispatch(root,{'action':'finish','run':'r','state':'SUCCEEDED','result':{'summary':'你好','response_mode':'RESEARCH','research':{}}},{},{})
            with closing(a.connect()) as c:
                row=c.execute("SELECT kind,payload FROM secretary_events WHERE occurrence='r:result'").fetchone()
            self.assertEqual(row[0],'CONVERSATION_REPLY');self.assertNotIn('research',json.loads(row[1]))
            store=IncidentStore(root/'runtime/recovery.sqlite3');reconcile_replies(a,store)
            self.assertEqual(store.claim()['payload']['message_role'],'CHAT');self.assertIsNone(store.claim())

if __name__=='__main__':unittest.main()
