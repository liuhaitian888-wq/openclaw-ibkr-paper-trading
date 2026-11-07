import asyncio
from contextlib import closing
from datetime import datetime,timezone
import html
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as V
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.notification_center import category,recipient,render,inbox,mark_read,preview,set_preference,get_item
from reporting.incident_telegram import send_one,verify_audience
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_queue import initialize,accept_update,claim
from reporting.secretary_controls import process_controls

CFG=dict(bot_token='123456:'+('x'*35),bot_username='deehub_paper_reports_bot',bot_id=9,chat_id=-100,
 expected_group_title='der',expected_member_count=2,owner_user_id=42,target_verified=True,
 audience_mode='shared_group',owner_private_chat_id=42,owner_private_verified=True,notification_format='compact-v1')

class NotificationCenterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.store=IncidentStore(self.root/'r.sqlite3',clock=lambda:1000);self.co=RecoveryCoordinator(self.store.path)
 def event(self,key='paper-safety:protection:PFE',occ='a',resolved=False,**payload):
  self.store.ingest(occ,key,dict(reason='<b>SECRET PFE 8 USD</b>',severity='GREEN' if resolved else 'RED',**payload),resolved=resolved)
  with closing(self.store.connect()) as c:return c.execute('SELECT max(id) FROM notification_outbox').fetchone()[0]
 def bot(self,fail_edit=False):
  class Bot:
   sends=[];edits=[];closed=False
   async def __aenter__(self):return self
   async def __aexit__(self,*a):self.closed=True
   async def get_me(self,**k):return V(id=9,username=CFG['bot_username'])
   async def get_chat(self,cid,**k):return V(id=cid,title='der' if cid<0 else None,type='supergroup' if cid<0 else 'private')
   async def get_chat_member_count(self,*a,**k):return 50
   async def get_chat_administrators(self,*a,**k):return [V(status='creator',user=V(id=42))]
   async def send_message(self,cid,**k):
    self.sends.append((cid,k));return V(chat=V(id=cid),message_id=77,date=datetime.now(timezone.utc))
   async def edit_message_text(self,**k):
    self.edits.append(k)
    if fail_edit:raise TimeoutError('ambiguous edit')
    return V(chat=V(id=k['chat_id']),message_id=k['message_id'],date=datetime.now(timezone.utc))
  return Bot()
 def send(self,bot,cfg=None):return asyncio.run(send_one(self.store,self.co,cfg or CFG,report_root=self.root,bot_factory=lambda **k:bot))
 def test_friends_do_not_gain_private_destinations_and_unknown_categories_are_private(self):
  ident=self.event();item=get_item(self.store,ident)
  self.assertEqual(recipient(item,CFG),42);self.assertEqual(category(item),'risk')
  self.assertEqual(self.send(self.bot()),'TELEGRAM_ACCEPTED')
  item['incident_key']='new-unclassified-producer';item['payload']['audience']='group'
  self.assertEqual(recipient(item,CFG),42)
  bot=self.bot();self.assertEqual(asyncio.run(verify_audience(bot,CFG)).id,-100)
 def test_group_summary_never_contains_payload_symbol_account_or_source_metadata(self):
  ident=self.event(key='paper-safety:upstream',account='DUQSECRET',symbol='PFE',quantity=8,source='PRIVATE_PATH')
  view=render(get_item(self.store,ident),CFG,1000)
  self.assertEqual(view['chat_id'],-100)
  for secret in ('DUQSECRET','PFE','PRIVATE_PATH','SECRET'):self.assertNotIn(secret,view['text']);self.assertNotIn(secret,view['html'])
  self.assertEqual(self.send(self.bot()),'TELEGRAM_ACCEPTED')
 def test_missing_owner_private_identity_never_falls_back_or_sends(self):
  self.event();cfg=dict(CFG,owner_private_verified=False);bot=self.bot()
  with self.assertRaises(PermissionError):self.send(bot,cfg)
  self.assertEqual(bot.sends,[])
 def test_owner_authorized_public_report_and_legacy_renderer_rejected(self):
  item={'id':1,'incident_key':'paper-safety:upstream','kind':'REPORT_BUNDLE','payload':{}}
  self.assertEqual(recipient(item,CFG),-100)
  from reporting.incident_telegram import validate_config
  cfg=dict(CFG);cfg.pop('notification_format')
  with self.assertRaises(PermissionError):validate_config(cfg)
 def test_private_target_verification_does_not_depend_on_group_availability(self):
  from reporting.incident_telegram import verify_destination
  bot=self.bot()
  async def chat(cid,**k):
   if cid<0:raise RuntimeError('group unavailable')
   return V(id=42,type='private')
  bot.get_chat=chat
  item={'id':1,'incident_key':'private','kind':'SECRETARY_REPLY','payload':{}}
  self.assertEqual(asyncio.run(verify_destination(bot,CFG,item)).id,42)
 def test_native_private_target_mismatch_is_unsent(self):
  self.event();bot=self.bot()
  async def wrong(*a,**k):return V(id=43,type='private')
  bot.get_chat=wrong
  self.assertEqual(self.send(bot),'PENDING');self.assertEqual(bot.sends,[]);self.assertFalse(self.co.uncertainties())
 def test_html_is_escaped_and_details_are_collapsible_with_plain_important_label(self):
  ident=self.event();view=render(get_item(self.store,ident),CFG,1000)
  self.assertIn('<blockquote expandable>',view['html']);self.assertIn('&lt;b&gt;SECRET',view['html'])
  self.assertNotIn('<b>SECRET',view['html']);self.assertNotIn('严重程度：',view['text']);self.assertIn('重要',view['text'])
 def test_preview_reads_without_claim_send_read_or_delivery_receipt(self):
  ident=self.event();text=preview(self.store,CFG,ident)
  self.assertIn('仅你的机器人私聊',text);self.assertIn('SECRET PFE',text)
  self.assertEqual(get_item(self.store,ident)['status'],'PENDING');self.assertIn('● 未读',inbox(self.store))
  with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_delivery').fetchone()[0],0)
 def test_new_state_stays_unread_and_inbox_collapses_incident_occurrence(self):
  ident=self.event();mark_read(self.store,ident);self.assertIn('○ 已读',inbox(self.store,'risk'))
  self.event(occ='b',resolved=True);text=inbox(self.store,'risk')
  self.assertEqual(text.count('来源：'),1);self.assertIn('● 未读',text);self.assertIn('RECOVERY',text)
 def test_preference_mutes_without_receipt_and_cannot_mute_critical(self):
  set_preference(self.store,'research','off')
  with closing(self.store.connect()) as c,c:c.execute("INSERT INTO notification_outbox VALUES (1,'secretary:one',1,'SECRETARY_REPLY',?,'PENDING')",(json.dumps({'reason':'study','message_role':'RESEARCH'}),))
  bot=self.bot();self.assertEqual(self.send(bot),'SUPPRESSED');self.assertEqual(bot.sends,[])
  with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_delivery').fetchone()[0],0)
  for cat in ('ops','risk','auth','control'):
   with self.assertRaises(ValueError):set_preference(self.store,cat,'off')
  self.event(occ='red');self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
 def test_recovery_edits_same_native_card_and_retains_both_receipts(self):
  self.event(key='paper-safety:upstream');bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
  self.event(key='paper-safety:upstream',occ='recovery',resolved=True)
  self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED');self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
  self.assertEqual(bot.edits[0]['message_id'],77)
  with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_receipts').fetchone()[0],2)
 def test_ambiguous_edit_is_not_replayed_or_replaced_with_new_message(self):
  self.event(key='paper-safety:upstream');bot=self.bot(fail_edit=True);self.send(bot)
  self.event(key='paper-safety:upstream',occ='recovery',resolved=True)
  self.assertEqual(self.send(bot),'UNKNOWN');self.assertEqual(self.send(bot),'BLOCKED_UNKNOWN')
  self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1);self.assertTrue(bot.closed)
 def test_owner_only_both_chats_and_deterministic_inbox_commands(self):
  archive=SecretaryArchive(self.root/'a.sqlite3');initialize(archive)
  for i,(cid,sender,text,allowed) in enumerate([(-100,43,'/holdings',False),(43,43,'/inbox',False),(42,42,'/inbox',True),(-100,42,'/notify',True),(42,42,'/start',True)]):
   u={'update_id':i,'message':{'chat':{'id':cid},'from':{'id':sender,'is_bot':False},'text':text,'date':1000,'message_id':i}}
   self.assertEqual(accept_update(archive,u,CFG,armed_at=1000),allowed)
  with patch('reporting.secretary_controls.subprocess.run') as start:process_controls(archive,self.root,CFG)
  start.assert_not_called();self.assertIsNone(claim(archive,model='gpt-6.1-sol',now=1000))
  with closing(archive.connect()) as c:self.assertEqual(c.execute("SELECT count(*) FROM secretary_runs WHERE model='PYTHON_CONTROL' AND state='SUCCEEDED'").fetchone()[0],3)
 def test_tokens_and_password_fields_are_redacted_from_model_and_message_views(self):
  from reporting.errors import redact
  secret=CFG['bot_token']
  self.assertEqual(redact({'bot_token':secret,'password':'fake-password'})['password'],'[REDACTED]')
  self.assertNotIn(secret,redact('https://api.telegram.org/bot'+secret+'/sendMessage'))
  item={'id':1,'incident_key':'report:today','generation':1,'kind':'REPORT_BUNDLE','payload':{'reason':'token: '+secret}}
  view=render(item,CFG,1000)
  self.assertNotIn(secret,view['text']);self.assertNotIn(secret,view['html'])
 def test_secretary_sql_cannot_bypass_credential_field_denial_with_alias_or_substring(self):
  import sqlite3
  from reporting.secretary_read import query
  with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c,c:
   c.execute('CREATE TABLE accidental_secret(password TEXT,bot_token TEXT)')
   c.execute('INSERT INTO accidental_secret VALUES (?,?)',('fake-password',CFG['bot_token']))
  for sql in ('SELECT password AS harmless FROM accidental_secret','SELECT substr(bot_token,1,4) AS harmless FROM accidental_secret'):
   with self.assertRaises(sqlite3.DatabaseError):query(self.root,'trading_audit.sqlite3',sql)
 def test_empty_reason_keeps_a_deliverable_notification(self):
  item={'id':1,'incident_key':'private','generation':1,'kind':'ALERT','payload':{'reason':''}}
  self.assertIn('状态已更新',render(item,CFG,1000)['text'])
 def test_report_caption_is_bounded_and_public_as_authorized(self):
  item={'id':1,'incident_key':'report:today','generation':1,'kind':'REPORT_BUNDLE','payload':{'reason':'日报'*1600}}
  view=render(item,CFG,1000);self.assertLess(len(view['text']),1024);self.assertEqual(view['chat_id'],-100)
