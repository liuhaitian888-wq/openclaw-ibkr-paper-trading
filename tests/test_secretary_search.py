import asyncio,json,sqlite3,tempfile,unittest
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as V
from reporting.secretary_search import search_records
from reporting.telegram_search import search,request_values
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize,accept_update,claim
from reporting.secretary_controls import process_controls,pending_controls,finish_search
from reporting.incidents import IncidentStore

class SearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
  self.a=SecretaryArchive(self.r/'agent_secretary.sqlite3');initialize(self.a)
  self.cfg={'owner_user_id':42,'chat_id':-10077,'bot_id':9,'bot_username':'fixture','owner_private_chat_id':42,'owner_private_verified':True}
 def test_existing_logs_search_is_bounded_readonly_and_redacted(self):
  for i in range(4):self.a.append('work:'+str(i),'der-secretary',origin='TOOL',kind='EXPERIMENT',payload={'text':'timeout issue','password':'fake-private'})
  data=search_records(self.r,{'source':'work','query':'timeout','limit':2})
  self.assertEqual(len(data['rows']),2);self.assertTrue(data['truncated']);self.assertNotIn('fake-private',str(data))
  nextpage=search_records(self.r,{'source':'work','query':'timeout','limit':2,'before_id':data['next_before_id']})
  self.assertEqual(len(nextpage['rows']),2);self.assertFalse(data['telegram_history_searched'])
  self.assertEqual(search_records(self.r,{'query':'% OR 1=1 --'})['rows'],[])
 def test_missing_user_session_never_calls_client_or_claims_search_completed(self):
  def factory(c):raise AssertionError('No client without approval')
  data=asyncio.run(search(self.r/'missing.json',{'query':'outage'},self.cfg,client_factory=factory))
  self.assertEqual(data['state'],'NEEDS_OWNER_USER_SESSION');self.assertFalse(data['history_mirrored'])
 def config(self):
  p=self.r/'search.json';p.write_text(json.dumps(dict(approved=True,owner_user_id=42,chat_id=-10077,api_id=123,api_hash='a'*32,session='fake-private-session',channel_access_hash=7)));p.chmod(0o600);return p
 def client(self,owner=42,authorized=True):
  class Client:
   closed=False;requests=[]
   async def connect(self):pass
   async def disconnect(self):self.closed=True
   async def is_user_authorized(self):return authorized
   async def get_me(self):return V(id=owner,bot=False)
   async def iter_messages(self,peer,**kw):
    self.requests.append((peer,kw))
    for sender,ident in [(43,10),(9,9),(88,8)]:yield V(id=ident,sender_id=sender,date=datetime.now(timezone.utc),message='password=example-private')
  return Client()
 def test_live_adapter_filters_humans_and_other_bots_and_closes_without_archive(self):
  p=self.config();client=self.client();expected={**self.cfg,'bot_ids':[9]}
  result=asyncio.run(search(p,{'query':'outage'},expected,client_factory=lambda c:client,peer_factory=lambda cid,h:(cid,h)))
  self.assertEqual(result['state'],'SEARCHED');self.assertEqual(len(result['rows']),1);self.assertEqual(result['rows'][0]['sender_id'],9)
  self.assertIn('https://t.me/c/77/9',result['rows'][0]['url']);self.assertNotIn('example-private',str(result))
  self.assertTrue(client.closed);self.assertEqual(client.requests[0][0],(77,7));self.assertEqual(len(list(self.r.glob('*.session'))),0)
 def test_wrong_owner_and_unapproved_target_never_search(self):
  p=self.config();client=self.client(owner=43);expected={**self.cfg,'bot_ids':[9]}
  with self.assertRaises(PermissionError):asyncio.run(search(p,{'query':'outage'},expected,client_factory=lambda c:client,peer_factory=lambda *a:a))
  self.assertTrue(client.closed);self.assertEqual(client.requests,[])
  with self.assertRaises(PermissionError):asyncio.run(search(p,{'query':'outage'},{**expected,'chat_id':-10099},client_factory=lambda c:client))
 def test_readonly_search_validation_rejects_global_or_write_requests(self):
  for req in ({'query':'x','chat_id':-200},{'query':'x','method':'send_message'},{'query':'x','limit':1000},{'query':''}):
   with self.assertRaises(ValueError):request_values(req)
 def test_unauthorized_session_does_not_attempt_login(self):
  client=self.client(authorized=False)
  result=asyncio.run(search(self.config(),{'query':'outage'},{**self.cfg,'bot_ids':[9]},client_factory=lambda c:client))
  self.assertEqual(result['state'],'NEEDS_OWNER_LOGIN');self.assertTrue(client.closed)
 def test_owner_search_queue_dispatches_once_and_unknown_auth_stays_explicit(self):
  u={'update_id':1,'message':{'chat':{'id':42,'type':'private'},'from':{'id':42,'is_bot':False},'date':1000,'message_id':1,'text':'/search outage'}}
  self.assertTrue(accept_update(self.a,u,self.cfg,armed_at=1000));process_controls(self.a,self.r,self.cfg)
  controls=pending_controls(self.a);self.assertEqual(controls[0]['kind'],'TELEGRAM_SEARCH');self.assertEqual(pending_controls(self.a),[])
  result={'state':'NEEDS_OWNER_USER_SESSION','rows':[],'reason':'Owner login needed'}
  request={'run':controls[0]['run'],'result':result};finish_search(self.a,self.r,request);finish_search(self.a,self.r,request)
  with closing(sqlite3.connect(self.r/'runtime/recovery.sqlite3')) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],1)
  self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=1000))
 def test_friend_cannot_queue_search(self):
  u={'update_id':1,'message':{'chat':{'id':42,'type':'private'},'from':{'id':43,'is_bot':False},'date':1000,'message_id':1,'text':'/search password'}}
  self.assertFalse(accept_update(self.a,u,self.cfg,armed_at=1000));self.assertEqual(pending_controls(self.a),[])


class CloudLedgerSearchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.archive=SecretaryArchive(self.root/'agent_secretary.sqlite3');initialize(self.archive)
  self.archive.append('owner-search','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'risk'})
  self.archive.reserve_run('owner-search:run',instruction='owner-search',model='gpt-6.1-sol')
  IncidentStore(self.root/'runtime/recovery.sqlite3').ingest('risk-fixture','risk-fixture',{'reason':'risk fixture'})
 def dispatch(self,req,step=1):
  from ops.cloud.secretary_rpc import dispatch
  return dispatch(self.root,{'action':'tool','run':'owner-search:run','step':step,'response_mode':'CHAT','request':req},{},{})
 def test_registered_ledger_sources_reach_readonly_dispatch_and_keep_results(self):
  for step,source in enumerate(('work','notifications'),1):
   req={'name':'search_records','source':source,'query':'risk','limit':10,'before_id':9223372036854775807}
   result=self.dispatch(req,step)
   self.assertEqual(result['state'],'READ_ONLY_RESULT');self.assertEqual(result['source'],source)
   self.assertTrue(result['rows']);self.assertFalse(result['telegram_history_searched'])
   self.assertEqual(self.dispatch(req,step),result)
  with closing(self.archive.connect()) as c:
   self.assertEqual(c.execute("SELECT count(*) FROM secretary_events WHERE kind='READ_ONLY_EXPERIMENT'").fetchone()[0],2)
 def test_other_tools_cannot_use_ledger_source_to_impersonate_origin(self):
  for req in ({'name':'query','source':'notifications'}, {'name':'search_records','source':'local_snapshot'}, {'name':'search_records','source':'telegram_live'}):
   with self.assertRaises(ValueError):self.dispatch(req)
