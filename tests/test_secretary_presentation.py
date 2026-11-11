import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive
from reporting.incidents import IncidentStore
from reporting.secretary_queue import initialize,accept_update,claim,progress,acknowledgement,enqueue_reply
from reporting.secretary_controls import process_controls
from reporting.secretary_presentation import reference,record_description,work_status
from reporting.notification_center import render

CFG=dict(owner_user_id=42,owner_private_chat_id=42,owner_private_verified=True,bot_username='fixture',bot_id=9,chat_id=-100,target_verified=True,audience_mode='shared_group')

class PresentationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:1000);initialize(self.a)
  self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:1000)
  self.i='telegram:42:15';self.run=self.i+':run'
  self.a.append(self.i,'der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'/research 研究持仓集中风险'})
 def reserve(self):self.a.reserve_run(self.run,instruction=self.i,model='gpt-6.1-sol')
 def test_reference_stable_short_and_receipt_does_not_claim_started(self):
  self.assertEqual(reference(self.i),reference(self.i));self.assertRegex(reference(self.i),r'^T[A-F0-9]{8}$')
  text=acknowledgement('cloud_oauth');self.assertIn('收到',text)
  for value in ('入库','云端','模型','已开始','Mac','数据库'):self.assertNotIn(value,text)
 def test_bare_work_is_a_real_readonly_command_and_no_unrelated_help(self):
  u={'update_id':16,'message':{'chat':{'id':42,'type':'private'},'from':{'id':42,'is_bot':False},'date':1000,'message_id':6,'text':'/work'}}
  accept_update(self.a,u,CFG,armed_at=1000);process_controls(self.a,self.root,CFG)
  with closing(self.store.connect()) as c:payload=json.loads(c.execute('SELECT payload FROM notification_outbox').fetchone()[0])
  text=payload['reason'];self.assertIn('研究持仓集中风险',text);self.assertIn('等待处理',text)
  for value in ('Supported commands','gate_apply','JSON','telegram:',':run'):self.assertNotIn(value,text)
 def test_claim_is_not_model_start_and_unknown_is_not_completed(self):
  self.reserve();self.assertIn('已接下，等待分析',work_status(self.a,self.store))
  self.a.append('started','der-secretary',origin='SYSTEM',kind='MODEL_STARTED',parent=self.i,payload={})
  self.assertIn('正在处理',work_status(self.a,self.store))
  self.a.finish_run(self.run,state='UNKNOWN');text=work_status(self.a,self.store)
  self.assertIn('结果待核对',text);self.assertNotIn('已回复',text)
 def test_one_business_acceptance_preserves_full_internal_tool_evidence(self):
  self.reserve();data={'response_mode':'RESEARCH','task_title':'持仓集中风险','task_brief':'比较各持仓占比，找出风险集中的地方'}
  for _ in range(2):record_description(self.a,self.store,self.run,self.i,{},data,announce=True)
  progress(self.store,self.run,'FIRST_TOOL','broker_query; None; '+self.run)
  self.a.append(self.run+':tool:1','der-secretary',origin='TOOL',kind='READ_ONLY_EXPERIMENT',parent=self.i,payload={'request':{'name':'broker_query'},'result':{'state':'READY'}})
  with closing(self.store.connect()) as c:
   rows=c.execute('SELECT id,incident_key,kind,payload FROM notification_outbox').fetchall()
  self.assertEqual(len(rows),1);p=json.loads(rows[0][3]);self.assertIn('研究已接下：持仓集中风险',p['reason']);self.assertIn('简介',p['reason'])
  item={'id':rows[0][0],'incident_key':rows[0][1],'kind':rows[0][2],'payload':p,'generation':1}
  view=render(item,CFG,1000)
  for value in ('broker_query','None','telegram:',':run','blockquote'):self.assertNotIn(value,view['html'])
  with closing(self.a.connect()) as c:self.assertIn('broker_query',c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(self.run+':tool:1',)).fetchone()[0])
 def test_short_reference_filters_work_and_chat_does_not_announce_research(self):
  self.reserve();text=work_status(self.a,self.store,reference(self.i));self.assertIn('研究持仓集中风险',text)
  self.assertIn('没有找到',work_status(self.a,self.store,'not-present'))
  record_description(self.a,self.store,self.run,self.i,{}, {'response_mode':'CHAT','summary':'你好'},announce=True)
  with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],0)
 def test_finished_and_delivered_are_independent(self):
  self.reserve();self.a.append('answer','der-secretary',origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',parent=self.i,payload={'summary':'结果','response_mode':'RESEARCH'})
  self.a.finish_run(self.run,state='SUCCEEDED',result_event='answer')
  self.assertIn('回复等待发送',work_status(self.a,self.store))
  self.assertNotIn('已回复',work_status(self.a,self.store))
  enqueue_reply(self.a,self.store,self.run,'结果')
  with closing(self.store.connect()) as c,c:
   c.execute("UPDATE notification_outbox SET status='TELEGRAM_ACCEPTED'")
  self.assertNotIn('回复已发送',work_status(self.a,self.store))
  with closing(self.store.connect()) as c,c:
   ident=c.execute('SELECT id FROM notification_outbox').fetchone()[0];c.execute('INSERT INTO notification_receipts VALUES (?,?)',(ident,json.dumps({'message_ids':[9]})))
  self.assertIn('回复已发送',work_status(self.a,self.store))
 def test_old_progress_is_sanitized_and_new_results_are_plain_and_escaped(self):
  item={'id':7,'incident_key':'secretary-progress:'+self.run,'kind':'SECRETARY_REPLY','generation':1,'payload':{'message_role':'PROGRESS','reason':'broker_query None '+self.run}}
  self.assertEqual(render(item,CFG,1000)['text'],'任务处理中。\n事件 #7')
  item['payload']={'message_role':'RESEARCH','reason':'实际结果 <tag>','task_title':'集中风险','task_ref':reference(self.i)}
  v=render(item,CFG,1000);self.assertIn('&lt;tag&gt;',v['html']);self.assertNotIn('blockquote',v['html']);self.assertEqual(v['audience'],'owner')

 def test_host_description_rpc_and_model_loop_use_acknowledged_business_fields(self):
  from ops.cloud.secretary_rpc import dispatch
  from scripts.run_secretary_bridge import execute
  job=claim(self.a,model='gpt-6.1-sol',now=1000)
  calls=[]
  def invoke(req):
   calls.append(req)
   return dispatch(self.root,req,CFG,{})
  def infer(*args,**kwargs):
   return {'response_mode':'RESEARCH','task_title':'集中风险研究','task_brief':'比较持仓占比和风险来源','summary':'先核对现有资料','tools':[{'name':'databases'}]},{}
  result=execute(job,{'codex':None,'codex_home':None,'empty_dir':None},invoke=invoke,inference=infer,cloud_only=True)
  self.assertEqual(result['state'],'YIELDED')
  with closing(self.a.connect()) as c:
   data=json.loads(c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(job['run']+':description',)).fetchone()[0])
   self.assertEqual(data['task_title'],'集中风险研究')
   self.assertEqual(c.execute("SELECT count(*) FROM secretary_events WHERE kind='READ_ONLY_EXPERIMENT'").fetchone()[0],1)
  with closing(self.store.connect()) as c:
   rows=c.execute('SELECT incident_key,payload FROM notification_outbox').fetchall()
  self.assertEqual(len(rows),1);self.assertTrue(rows[0][0].startswith('secretary-task-start:'))
  self.assertNotIn('databases',json.loads(rows[0][1])['reason'])
 def test_explicit_chat_cannot_be_announced_as_research_by_host_rpc(self):
  from ops.cloud.secretary_rpc import dispatch
  self.a.append('chat','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'/chat 讨论一下研究'})
  self.a.reserve_run('chat:run',instruction='chat',model='gpt-6.1-sol')
  result=dispatch(self.root,{'action':'task_description','run':'chat:run','description':{'response_mode':'RESEARCH','task_title':'不应立项'},'announce':True},CFG,{})
  self.assertEqual(result['state'],'NOT_A_TASK')
