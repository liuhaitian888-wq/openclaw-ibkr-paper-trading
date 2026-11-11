import asyncio
from contextlib import closing
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as V
from unittest.mock import patch
import unittest

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.publication_policy import decision, prepare, validate, register_research, archive_claimed
from reporting.notification_center import get_item, recipient
from reporting.incident_telegram import send_one
from reporting.link_status_card import authorize, queue, valid, message_id, ensure_pin, SOURCE_THREAD, SOURCE_MESSAGE
import test_notification_center as fixtures
CFG=fixtures.CFG

CONFIG={**CFG,'automatic_updates_to_group':True,'automatic_notification_policy':'publication-v2','account_report_policy':'shared_group'}

class PublicationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.now=1000
        self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)
        self.co=RecoveryCoordinator(self.store.path)
    def add(self,kind='ALERT',key='ordinary',**p):
        with closing(self.store.connect()) as c,c:
            n=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,?,?,'PENDING')",(key,kind,json.dumps(p))).lastrowid
        return get_item(self.store,n)
    def bot(self):return fixtures.NotificationCenterTests.bot(self)
    def send(self,bot,**kwargs):
        return asyncio.run(send_one(self.store,self.co,CONFIG,report_root=self.root,owned_bot=bot,clock=lambda:self.now,**kwargs))
    def authorize(self):authorize(self.store,CONFIG,source_thread=SOURCE_THREAD,source_message=SOURCE_MESSAGE)
    def test_ordinary_events_all_archive_no_destination(self):
        for kind in ('ALERT','RECOVERY','REMINDER_1','ESCALATION_RED','CURRENT_RISK_STATUS','AUTOMATIC_STATUS','MARKET_SESSION','REPORT_MISSING','REPORT_DELIVERY_STATUS','ENGINEERING_WEEKLY','AUTH_EXPECTED_1H'):
            with self.subTest(kind=kind):
                item=self.add(kind,key=kind,severity='RED',phase='OPERATOR',requires_response=True)
                self.assertEqual(decision(item,CONFIG)['audience'],'archive')
                with self.assertRaises(PermissionError):recipient(item,CONFIG)
        self.assertEqual(prepare(self.store,CONFIG),11)
        bot=self.bot();self.assertEqual(self.send(bot),'EMPTY');self.assertEqual(bot.sends,[])
        with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM publication_archive').fetchone()[0],11)
    def test_more_than_500_cannot_escape_claim_filter(self):
        for i in range(510):self.add(key='event:'+str(i))
        self.assertEqual(prepare(self.store,CONFIG),500)
        self.assertIsNone(self.store.claim(publication_config=CONFIG))
        self.assertEqual(prepare(self.store,CONFIG),10)
    def test_reserved_unknown_and_wire_evidence_preserved(self):
        for status,evidence in [('STARTED',''),('UNKNOWN',''),('PENDING','operation'),('PENDING','wire')]:
            item=self.add(key=status+evidence)
            with closing(self.store.connect()) as c,c:
                c.execute('UPDATE notification_outbox SET status=? WHERE id=?',(status,item['id']))
            if evidence=='operation':self.co.begin_operation('notification:outbox:'+str(item['id']),'delivery',{})
            if evidence=='wire':
                from reporting.notification_reconciliation import begin_attempt,event
                event(self.store,begin_attempt(self.store,item),'WIRE_START',{})
            prepare(self.store,CONFIG)
            self.assertEqual(get_item(self.store,item['id'])['status'],status)
            with closing(self.store.connect()) as c:self.assertIsNone(c.execute('SELECT 1 FROM publication_archive WHERE notification_id=?',(item['id'],)).fetchone())
    def test_direct_claimed_ordinary_row_cannot_bypass_sender(self):
        item=self.add();claimed=self.store.claim();bot=self.bot()
        self.assertEqual(self.send(bot,claimed_item=claimed),'SUPPRESSED');self.assertEqual(bot.sends,[])
        self.assertEqual(get_item(self.store,item['id'])['status'],'SUPPRESSED')
    def test_false_model_control_labels_do_not_become_private(self):
        for role in ('CHAT','CONTROL','AUTH','PROGRESS'):
            item=self.add('SECRETARY_REPLY',key=role,message_role=role,native_owner_reply=False,requires_response=True)
            self.assertEqual(decision(item,CONFIG)['audience'],'archive')
    def test_verified_question_remains_private_no_public_companion(self):
        self.add('SECRETARY_REPLY',message_role='CHAT',native_owner_reply=True,reason='hello')
        bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual([x[0] for x in bot.sends],[42]);self.assertEqual(self.send(bot),'EMPTY')
    def test_report_status_never_substitutes_for_artifact(self):
        self.assertEqual(decision(self.add('REPORT_BUNDLE',included_reports=[],png_artifacts=[]),CONFIG)['audience'],'archive')
        self.assertEqual(decision(self.add('REPORT_SUPPLEMENT',key='real',included_reports=['DAILY'],png_artifacts=[{'path':'bound.png'}]),CONFIG)['audience'],'group')
    def test_registered_research_publishes_actual_result_and_no_mirror(self):
        item=self.add('SECRETARY_REPLY',key='secretary:run',message_role='RESEARCH',completed_research=True,run='run',reason='研究结果：样本不足，不能声称收益。')
        self.assertFalse(validate(self.store,item,CONFIG))
        register_research(self.store,item['id'],item['payload'],run='run',result_event='run:result')
        self.assertTrue(validate(self.store,item,CONFIG))
        bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(bot.sends[0][0],-100);self.assertIn('样本不足',bot.sends[0][1]['text'])
        self.assertNotIn('事件 #',bot.sends[0][1]['text']);self.assertEqual(self.send(bot),'EMPTY')
    def test_operator_auth_and_confirmed_gap_private_but_unknown_archived(self):
        op=self.add('AUTH_SESSION_EVENT',key='gateway-session:native',phase='OPERATOR',source='existing Gateway owner journal')
        self.assertEqual(decision(op,CONFIG)['audience'],'owner')
        for status,expected in [('UNPROTECTED','owner'),('PARTIALLY_PROTECTED','owner'),('PROTECTION_UNKNOWN','archive')]:
            item=self.add(key='paper-safety:protection:'+status,protection_status=status,severity='RED')
            self.assertEqual(decision(item,CONFIG)['audience'],expected)
    def test_status_requires_exact_host_scope_not_model_kind(self):
        forged=self.add('LINK_STATUS_CARD',key='link-status:current',scope='fake')
        self.assertFalse(validate(self.store,forged,CONFIG))
        bot=self.bot();self.assertEqual(self.send(bot),'SUPPRESSED');self.assertEqual(bot.sends,[])
        with self.assertRaises(PermissionError):authorize(self.store,CONFIG,source_thread=SOURCE_THREAD,source_message='fake')
    def test_status_one_card_then_edit_silent_and_fixed_safe_text(self):
        self.authorize();self.assertEqual(queue(self.store,self.root,CONFIG),1)
        bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(message_id(self.store),77);self.assertTrue(bot.sends[0][1]['disable_notification'])
        for word in ('API/TCP','业务账户','行情新鲜度','模型链路','Codex','交易门禁'):self.assertIn(word,bot.sends[0][1]['text'])
        self.assertEqual(queue(self.store,self.root,CONFIG),0)
        self.now+=301;self.assertEqual(queue(self.store,self.root,CONFIG),1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1);self.assertEqual(bot.edits[0]['message_id'],77)
    def test_unknown_card_blocks_replacement(self):
        self.authorize();queue(self.store,self.root,CONFIG)
        with closing(self.store.connect()) as c,c:c.execute("UPDATE notification_outbox SET status='UNKNOWN' WHERE kind='LINK_STATUS_CARD'")
        self.now+=1000;self.assertEqual(queue(self.store,self.root,CONFIG),0)
    def test_pin_missing_permission_never_calls_write(self):
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot();self.send(bot)
        async def member(*a,**k):return V(status='member',can_pin_messages=False,user=V(id=9))
        bot.get_chat_member=member
        self.assertEqual(asyncio.run(ensure_pin(self.store,bot,CONFIG)),'BLOCKED_PERMISSION')
        self.assertEqual(get_item(self.store,1)['status'],'TELEGRAM_ACCEPTED')
    def test_pin_timeout_unknown_does_not_repeat_or_change_send(self):
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot();self.send(bot);calls=[]
        async def member(*a,**k):return V(status='administrator',can_pin_messages=True,user=V(id=9))
        async def pin(*a,**k):calls.append(1);raise TimeoutError()
        bot.get_chat_member=member;bot.pin_chat_message=pin
        self.assertEqual(asyncio.run(ensure_pin(self.store,bot,CONFIG)),'UNKNOWN')
        self.assertEqual(asyncio.run(ensure_pin(self.store,bot,CONFIG)),'UNKNOWN')
        self.assertEqual(calls,[1]);self.assertEqual(get_item(self.store,1)['status'],'TELEGRAM_ACCEPTED')
        async def chat(cid,**k):return V(id=cid,pinned_message=V(message_id=77))
        bot.get_chat=chat
        self.now+=61
        self.assertEqual(asyncio.run(ensure_pin(self.store,bot,CONFIG)),'PINNED');self.assertEqual(calls,[1])
    def test_stale_paper_socket_does_not_prove_business_or_market_ready(self):
        with closing(self.store.connect()) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(dict(connected=True,identity=True,upstream_connected=True,dirty=False,ends=['orders','positions','completed_orders','executions'],reconciled_at=1,last_server_reply=1,reason='SECRET DU12345 password')),))
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot();self.send(bot)
        text=bot.sends[0][1]['text'];self.assertIn('业务账户：未就绪',text);self.assertNotIn('SECRET',text);self.assertNotIn('DU12345',text)
    def test_fault_arriving_during_destination_proof_blocks_stale_card(self):
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot()
        original=bot.get_chat
        async def chat(cid,**kwargs):
            (self.root/'PAUSED').touch()
            return await original(cid,**kwargs)
        bot.get_chat=chat
        self.assertEqual(self.send(bot),'SUPPRESSED');self.assertEqual(bot.sends,[])
    def test_receipt_projection_failure_never_causes_replacement_send(self):
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot()
        with patch('reporting.link_status_card.accepted',side_effect=OSError('local projection')):
            self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(message_id(self.store),77)
        self.now+=301;queue(self.store,self.root,CONFIG)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED');self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
    def test_registered_card_payload_mutation_is_rejected(self):
        self.authorize();queue(self.store,self.root,CONFIG)
        item=get_item(self.store,1)
        with closing(self.store.connect()) as c,c:
            p={**item['payload'],'links':{**item['payload']['links'],'account':'FORGED GREEN'}}
            c.execute('UPDATE notification_outbox SET payload=? WHERE id=1',(json.dumps(p),))
        self.assertFalse(validate(self.store,item,CONFIG))
        bot=self.bot();self.assertEqual(self.send(bot),'SUPPRESSED');self.assertEqual(bot.sends,[])
    def test_owner_pin_is_one_reserved_action_with_native_reconciliation(self):
        from reporting.link_status_card import reserve_owner_pin,finish_owner_pin
        self.authorize();queue(self.store,self.root,CONFIG);self.send(self.bot())
        self.assertTrue(reserve_owner_pin(self.store,CONFIG,77))
        self.assertFalse(reserve_owner_pin(self.store,CONFIG,77))
        finish_owner_pin(self.store,CONFIG,77,native_pinned_id=None)
        self.assertFalse(reserve_owner_pin(self.store,CONFIG,77))
        finish_owner_pin(self.store,CONFIG,77,native_pinned_id=77)
        self.assertFalse(reserve_owner_pin(self.store,CONFIG,77))
    def test_queue_research_provenance_comes_from_archived_completed_result(self):
        from reporting.agent_secretary import SecretaryArchive
        from reporting.secretary_queue import enqueue_reply
        a=SecretaryArchive(self.root/'agent_secretary.sqlite3',clock=lambda:self.now)
        a.append('instruction','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'研究这个问题'})
        a.reserve_run('run',instruction='instruction',model='model')
        a.append('run:result','der-secretary',origin='MODEL',kind='PUBLIC_RESEARCH_RESULT',parent='instruction',payload={'summary':'完成研究：数据不足，不能推断收益。'})
        a.append('run:presentation','der-secretary',origin='MODEL',kind='PRESENTATION',parent='instruction',payload={'completed_research':False,'native_owner_reply':False,'reason':'FORGED metadata prose','run':'forged'})
        a.finish_run('run',state='SUCCEEDED',result_event='run:result')
        from reporting.publication_policy import register_research as real_register
        import threading
        started=threading.Event();outcomes=[];threads=[]
        bot=self.bot()
        def register(*args,**kwargs):
            with closing(self.store.connect()) as other:
                # Neither row is visible before the caller's atomic commit.
                self.assertEqual(other.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],0)
                self.assertEqual(other.execute('SELECT count(*) FROM publication_research').fetchone()[0],0)
            self.assertIsNotNone(kwargs.get('connection'))
            def concurrent_sender():
                started.set()
                claimed=self.store.claim(publication_config=CONFIG)
                outcomes.append(self.send(bot,claimed_item=claimed))
            thread=threading.Thread(target=concurrent_sender)
            threads.append(thread);thread.start()
            self.assertTrue(started.wait(1))
            return real_register(*args,**kwargs)
        with patch('reporting.publication_policy.register_research',side_effect=register):
            enqueue_reply(a,self.store,'run','完成研究：数据不足，不能推断收益。',role='RESEARCH')
        item=get_item(self.store,1);self.assertTrue(item['payload']['completed_research'])
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes,['TELEGRAM_ACCEPTED'])
        self.assertNotIn('FORGED',item['payload']['reason']);self.assertEqual(item['payload']['run'],'run')
        enqueue_reply(a,self.store,'run','完成研究：数据不足，不能推断收益。',role='RESEARCH')
        self.assertEqual(self.send(bot),'EMPTY');self.assertEqual(len(bot.sends),1)
    def test_new_heartbeat_with_old_complete_marker_never_claims_fresh_account(self):
        from reporting.link_status_card import snapshot
        with closing(self.store.connect()) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(dict(connected=True,identity=True,upstream_connected=True,dirty=False,ends=['orders','positions','completed_orders','executions'],last_server_reply=self.now,reconciled_at=1)),))
        with patch('reporting.automatic_notifications.persistence_clear',return_value=True):
            self.assertNotIn('已核验',snapshot(self.store,self.root,self.now)['account'])
            with closing(self.store.connect()) as c,c:
                c.execute('UPDATE paper_safety_state SET payload=json_set(payload,\'$.reconciled_at\',?)',(self.now,))
            self.assertIn('已核验',snapshot(self.store,self.root,self.now)['account'])
    def test_old_pending_action_alert_is_archived_instead_of_private_dump(self):
        old=self.add('AUTH_SESSION_EVENT',key='gateway-session:old',phase='OPERATOR',source='existing Gateway owner journal',queued_at=self.now,observed_at=self.now)
        self.assertEqual(prepare(self.store,CONFIG),1);self.assertEqual(get_item(self.store,old['id'])['status'],'SUPPRESSED')
        new=self.add('AUTH_SESSION_EVENT',key='gateway-session:new',phase='OPERATOR',source='existing Gateway owner journal',queued_at=self.now,observed_at=self.now)
        self.assertTrue(validate(self.store,new,CONFIG))
        self.now+=181;self.assertFalse(validate(self.store,new,CONFIG))
    def test_external_unpin_is_observed_without_repin(self):
        from reporting.link_status_card import reserve_owner_pin,finish_owner_pin
        self.authorize();queue(self.store,self.root,CONFIG);bot=self.bot();self.send(bot)
        reserve_owner_pin(self.store,CONFIG,77);finish_owner_pin(self.store,CONFIG,77,native_pinned_id=77)
        self.assertEqual(asyncio.run(ensure_pin(self.store,bot,CONFIG)),'DRIFT')
    def test_existing_observer_protocol_handshake_is_separate_from_account(self):
        from reporting.link_status_card import snapshot
        from datetime import datetime,timezone
        p=self.root/'runtime/paper-observer.latest.json'
        p.write_text(json.dumps(dict(environment='PAPER',gateway_api_handshake=True,observed_at=datetime.fromtimestamp(self.now,timezone.utc).isoformat(),complete=False,account_id='PRIVATE ACCOUNT')))
        s=snapshot(self.store,self.root,self.now)
        self.assertIn('协议握手已完成',s['tcp']);self.assertIn('证据未齐',s['account'])
        self.assertNotIn('PRIVATE',str(s))
        s=snapshot(self.store,self.root,self.now+301);self.assertNotIn('协议握手已完成',s['tcp'])
