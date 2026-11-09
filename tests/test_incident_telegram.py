import asyncio
from contextlib import closing
from datetime import datetime,timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace as V
import tempfile
import unittest
from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.incident_telegram import send_one


class TelegramTests(unittest.TestCase):
 def setup_case(self,tmp):
  root=Path(tmp);store=IncidentStore(root/'r.sqlite3');co=RecoveryCoordinator(store.path)
  png=root/'daily.png';content=b'\x89PNG\r\n\x1a\nfixture';png.write_bytes(content)
  payload=dict(delivery_transport='telegram',reason='actual report fixture',png_artifacts=[dict(path=str(png),sha256=hashlib.sha256(content).hexdigest())])
  import json
  with closing(store.connect()) as c,c:c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES ('daily',1,'REPORT_BUNDLE',?,'PENDING')",(json.dumps(payload),))
  cfg=dict(bot_token='123456:'+('x'*35),bot_username='deehub_paper_reports_bot',bot_id=9,chat_id=-100,expected_group_title='der',expected_member_count=2,owner_user_id=42,target_verified=True)
  return root,store,co,cfg,png
 def bot(self,*,fail=False,count=2):
  class Bot:
   sends=0;closed=False
   async def __aenter__(self):return self
   async def __aexit__(self,*a):self.closed=True
   async def get_me(self,**k):return V(id=9,username='deehub_paper_reports_bot')
   async def get_chat(self,*a,**k):return V(id=-100,title='der',type='group')
   async def get_chat_member_count(self,*a,**k):return count
   async def get_chat_administrators(self,*a,**k):return [V(status='creator',user=V(id=42))]
   async def send_document(self,*a,**k):
    self.sends+=1
    if fail:raise TimeoutError('Ambiguous outcome; no automatic fallback')
    return V(chat=V(id=-100),message_id=77,date=datetime.now(timezone.utc))
  return Bot()
 def test_native_ack_and_receipt_once_with_closed_client(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot()
   self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'TELEGRAM_ACCEPTED')
   self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'EMPTY')
   self.assertEqual(bot.sends,1);self.assertTrue(bot.closed)
   with closing(store.connect()) as c:
    self.assertEqual(c.execute('SELECT count(*) FROM notification_receipts').fetchone()[0],1)
    self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0],'TELEGRAM_ACCEPTED')
 def test_timeout_after_send_never_replays_or_switches_transport(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot(fail=True)
   self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'UNKNOWN')
   self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'BLOCKED_UNKNOWN')
   self.assertEqual(bot.sends,1);self.assertTrue(bot.closed)
   self.assertEqual(co.uncertainties()[0][2],'UNKNOWN')
 def test_changed_audience_or_png_proves_unsent(self):
  for condition in ('audience','png'):
   with self.subTest(condition=condition),tempfile.TemporaryDirectory() as tmp:
    root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot(count=3 if condition=='audience' else 2)
    if condition=='png':png.write_bytes(b'changed')
    result=asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot))
    self.assertEqual(result,'PENDING');self.assertEqual(bot.sends,0);self.assertFalse(co.uncertainties())
 def test_group_identity_requires_validated_config(self):
  with tempfile.TemporaryDirectory() as tmp:
   root,store,co,cfg,png=self.setup_case(tmp);cfg['target_verified']=False
   with self.assertRaises(PermissionError):asyncio.run(send_one(store,co,cfg,report_root=root))
   with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT status FROM notification_outbox').fetchone()[0],'PENDING')
 def test_operational_alert_and_missing_report_use_text_and_do_not_replay(self):
  for kind in ('ALERT','RECOVERY','REMINDER_1','AUTH_EXPECTED_1H','REPORT_BUNDLE'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
    root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot()
    async def text_send(*args,**kwargs):
     bot.sends+=1
     self.assertIn('实际发送发起',kwargs['text'])
     return V(chat=V(id=-100),message_id=78,date=datetime.now(timezone.utc))
    bot.send_message=text_send
    import json
    payload=dict(reason='缺报或故障',queued_at=1,scheduled_at=2,included_reports=[],png_artifacts=[])
    with closing(store.connect()) as c,c:
     c.execute('UPDATE notification_outbox SET kind=?,payload=?',(kind,json.dumps(payload)))
    self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'TELEGRAM_ACCEPTED')
    self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'EMPTY')
    self.assertEqual(bot.sends,1)

 def test_explicit_healthchecks_member_supergroup_and_native_ack(self):
  from reporting.incident_telegram import verify_audience
  with tempfile.TemporaryDirectory() as tmp:
   root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot(count=3)
   cfg.update(expected_member_count=3,allowed_additional_bots=[dict(id=88,username='HealthchecksBot')])
   async def chat(*a,**k):return V(id=-100,title='der',type='supergroup')
   async def member(cid,uid,**k):return V(status='member',user=V(id=uid,username='HealthchecksBot' if uid==88 else cfg['bot_username'],is_bot=True))
   bot.get_chat=chat;bot.get_chat_member=member
   self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'TELEGRAM_ACCEPTED')
   self.assertEqual(bot.sends,1)
 def test_extra_identity_admin_human_or_fourth_member_never_sends(self):
  for bad in ('username','human','admin','fourth','id','owner'):
   with self.subTest(bad=bad),tempfile.TemporaryDirectory() as tmp:
    root,store,co,cfg,png=self.setup_case(tmp);bot=self.bot(count=4 if bad=='fourth' else 3)
    cfg.update(expected_member_count=3,allowed_additional_bots=[dict(id=88,username='HealthchecksBot')])
    async def member(cid,uid,**k):return V(status='administrator' if uid==88 and bad=='admin' else 'member',user=V(id=89 if uid==88 and bad=='id' else uid,username='impostor' if bad=='username' else 'HealthchecksBot',is_bot=bad!='human'))
    bot.get_chat_member=member
    if bad=='owner':
     async def admins(*a,**k):return [V(status='creator',user=V(id=43))]
     bot.get_chat_administrators=admins
    self.assertEqual(asyncio.run(send_one(store,co,cfg,report_root=root,bot_factory=lambda **k:bot)),'PENDING')
    self.assertEqual(bot.sends,0);self.assertFalse(co.uncertainties())
 def test_unapproved_audience_config_cannot_expand_membership(self):
  from reporting.incident_telegram import validate_config
  with tempfile.TemporaryDirectory() as tmp:
   root,store,co,cfg,png=self.setup_case(tmp)
   cfg['expected_member_count']=3
   with self.assertRaises(PermissionError):validate_config(cfg)
   cfg['allowed_additional_bots']=[dict(id=42,username='HealthchecksBot')]
   with self.assertRaises(PermissionError):validate_config(cfg)
   cfg['allowed_additional_bots']=[dict(id=88,username='AnotherBot')]
   with self.assertRaises(PermissionError):validate_config(cfg)

class ReviewedTitleTests(unittest.TestCase):
 def test_only_reviewed_titles_preserve_native_identity_requirements(self):
  from reporting.incident_telegram import validate_config
  from test_notification_center import CFG
  validate_config(dict(CFG,expected_group_title='deehub'))
  for change in ({'expected_group_title':'unexpected'}, {'target_verified':False}, {'owner_private_verified':False}):
   with self.assertRaises(PermissionError):validate_config(dict(CFG,**change))
