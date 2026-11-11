import asyncio
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.automatic_notifications import prepare, valid
from reporting.incidents import IncidentStore
from reporting.notification_access import decision
from reporting.notification_center import get_item, render
from reporting.incident_telegram import send_one, validate_config
from reporting.notification_reconciliation import begin_attempt, event, notice_batch
from reporting.recovery import RecoveryCoordinator
import test_notification_center as center_fixtures
from test_notification_center import CFG

CONFIG = {**CFG, 'automatic_updates_to_group':True,
          'automatic_notification_policy':'grouped-v1', 'account_report_policy':'shared_group'}


class AutomaticNotificationsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.now = 1000
        self.store = IncidentStore(self.root/'recovery.sqlite3', clock=lambda:self.now)
        self.co = RecoveryCoordinator(self.store.path)
        guard=patch('reporting.automatic_notifications.persistence_clear',return_value=True)
        guard.start();self.addCleanup(guard.stop)
        prepare(self.store, CONFIG)  # Persist cutover before new observations.
        self.now += 1

    def source(self, symbol='AAPL', suffix='', resolved=False, status='PROTECTION_UNKNOWN'):
        key = 'paper-safety:protection:'+symbol
        self.store.ingest(symbol+':'+str(self.now)+suffix, key,
            dict(reason='PRIVATE account DU1234567 secret diagnostic', symbol=symbol,
                 severity='GREEN' if resolved else 'RED', protection_status=status), resolved=resolved)
        with closing(self.store.connect()) as c:
            return c.execute('SELECT max(id) FROM notification_outbox').fetchone()[0]

    def summaries(self):
        with closing(self.store.connect()) as c:
            return [get_item(self.store, ident) for ident, in c.execute("SELECT id FROM notification_outbox WHERE kind='AUTOMATIC_STATUS' ORDER BY id")]

    def flush(self, seconds=2):
        prepare(self.store, CONFIG); self.now += seconds
        return prepare(self.store, CONFIG)

    def fresh(self,epoch='test-epoch'):
        with closing(self.store.connect()) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS paper_safety_state (id INTEGER PRIMARY KEY,payload TEXT)')
            p=dict(connected=True,identity=True,upstream_connected=True,dirty=False,
                   epoch=epoch,
                   ends=['orders','positions','completed_orders','executions'],
                   last_server_reply=self.now,reconciled_at=self.now)
            c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES (1,?)',(json.dumps(p),))

    def stabilize(self,seconds=60):
        self.now+=1;self.fresh();prepare(self.store,CONFIG)
        created=0
        for _ in range(seconds//5):
            self.now+=5;self.fresh();created+=prepare(self.store,CONFIG)
        return created

    def bot(self):
        return center_fixtures.NotificationCenterTests.bot(self)

    def send(self, bot):
        return asyncio.run(send_one(self.store,self.co,CONFIG,report_root=self.root,
                                   owned_bot=bot,clock=lambda:self.now))

    def test_seven_faults_one_group_card_safe_template_and_retained_sources(self):
        ids=[self.source(x) for x in ['AAPL','META','MSFT','PFE','T','NIO','NVDA']]
        self.assertEqual(self.flush(),1)
        summaries=self.summaries(); self.assertEqual(len(summaries),1)
        self.assertEqual(summaries[0]['payload']['open_count'],7)
        view=render(summaries[0],CONFIG,self.now)
        self.assertEqual(view['chat_id'],-100)
        for forbidden in ['DU1234567','PRIVATE','secret diagnostic','AAPL']:
            self.assertNotIn(forbidden,view['text'])
        self.assertIn('券商服务器连接',view['text'])
        for ident in ids:self.assertEqual(get_item(self.store,ident)['status'],'SUPPRESSED')
        bot=self.bot(); self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1); self.assertEqual(bot.sends[0][0],-100)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM automatic_notification_sources WHERE aggregate_id=?',(summaries[0]['id'],)).fetchone()[0],7)
        self.assertEqual(self.send(bot),'EMPTY')  # No automatic private mirror.

    def test_recovery_requires_stability_and_fresh_evidence_then_edits_same_card(self):
        self.source(); self.flush(); bot=self.bot(); self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.now+=1; self.source(resolved=True,status='PROTECTED'); prepare(self.store,CONFIG)
        self.now+=59; self.fresh(); self.assertEqual(prepare(self.store,CONFIG),0)
        self.assertEqual(self.stabilize(),1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1); self.assertEqual(len(bot.edits),1)
        self.assertEqual(bot.edits[0]['chat_id'],-100)
        self.assertEqual(bot.edits[0]['message_id'],77)
        self.assertIn('恢复汇总',bot.edits[0]['text'])
        self.assertFalse(self.summaries()[-1]['payload']['grants_trading_permission'])

    def test_repeated_faults_limited_across_restart_but_confirmed_gap_escalates(self):
        self.source();self.source('META'); self.flush(); bot=self.bot(); self.send(bot)
        self.now+=5; self.source('META'); self.assertEqual(self.flush(),0)
        self.store=IncidentStore(self.store.path,clock=lambda:self.now)
        self.now+=5; self.assertEqual(prepare(self.store,CONFIG),0)
        self.now+=1; self.source('META','confirmed',status='UNPROTECTED')
        self.assertEqual(self.flush(),1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1); self.assertEqual(len(bot.edits),1)
        self.now+=900; self.assertEqual(prepare(self.store,CONFIG),1)

    def test_recurrence_invalidates_pending_recovery_before_wire(self):
        self.source(); self.flush(); self.send(self.bot())
        self.now+=1; self.source(resolved=True,status='PROTECTED'); prepare(self.store,CONFIG)
        self.stabilize()
        recovery=self.summaries()[-1]
        self.now+=1; self.source(suffix='new')
        self.assertFalse(valid(self.store,recovery,self.now))
        self.assertEqual(self.send(self.bot()),'EMPTY')
        self.assertEqual(get_item(self.store,recovery['id'])['status'],'SUPPRESSED')

    def test_cutover_retains_old_pending_and_never_changes_uncertain_or_wire_rows(self):
        old=self.source(); uncertain=self.source('META')
        with closing(self.store.connect()) as c,c:
            c.execute("DELETE FROM incident_cursors WHERE source='automatic-policy:grouped-v1'")
            c.execute("UPDATE notification_outbox SET status='UNKNOWN' WHERE id=?",(uncertain,))
            original=c.execute('SELECT payload FROM notification_outbox WHERE id=?',(uncertain,)).fetchone()[0]
        self.now+=1; prepare(self.store,CONFIG)
        self.assertEqual(get_item(self.store,old)['status'],'SUPPRESSED')
        self.assertEqual(get_item(self.store,uncertain)['status'],'UNKNOWN')
        self.assertEqual(self.summaries(),[])
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT payload FROM notification_outbox WHERE id=?',(uncertain,)).fetchone()[0],original)
            self.assertEqual(c.execute('SELECT disposition FROM automatic_notification_sources WHERE notification_id=?',(old,)).fetchone()[0],'cutover_retained')
        self.now+=1; attempted=self.source('PFE'); item=get_item(self.store,attempted)
        a=begin_attempt(self.store,item); event(self.store,a,'WIRE_START',{})
        self.now+=1; prepare(self.store,CONFIG)
        self.assertEqual(get_item(self.store,attempted)['status'],'PENDING')

    def test_unknown_group_never_replays_or_opens_new_group_generation(self):
        self.source(); self.flush()
        item=self.store.claim(); self.store.delivery_started(item['id'],self.now)
        self.store.finish(item['id'],'UNKNOWN')
        self.now+=1000; self.source('META'); self.assertEqual(self.flush(),0)
        self.assertIsNone(self.store.claim()); self.assertEqual(len(self.summaries()),1)

    def test_recovery_keeps_old_member_uncertainty_guard(self):
        original=self.source(); self.store.claim(); self.store.finish(original,'UNKNOWN')
        self.now+=1; self.source(resolved=True,status='PROTECTED'); prepare(self.store,CONFIG)
        self.stabilize()
        self.assertEqual(self.summaries()[-1]['payload']['phase'],'RECOVERED')
        self.assertIsNone(self.store.claim())
        self.assertEqual(get_item(self.store,original)['status'],'UNKNOWN')

    def test_persistence_fault_blocks_recovery_with_otherwise_fresh_complete_state(self):
        self.source();self.flush();self.send(self.bot())
        self.now+=1;self.source(resolved=True,status='PROTECTED');prepare(self.store,CONFIG)
        with patch('reporting.automatic_notifications.persistence_clear',return_value=False):
            self.assertEqual(self.stabilize(),0)
        self.assertEqual(self.stabilize(),1)
        recovery=self.summaries()[-1]
        with patch('reporting.automatic_notifications.persistence_clear',return_value=False):
            self.assertFalse(valid(self.store,recovery,self.now))

    def test_automatic_review_and_auth_go_group_interaction_stays_private(self):
        for role in ['ACK','CHAT','CONTROL','AUTH']:
            item=dict(id=1,kind='SECRETARY_REPLY',incident_key='secretary:direct',payload={'message_role':role,'reason':'private'})
            self.assertEqual(decision(item,CONFIG)['audience'],'owner')
        for kind,p in [('AUTH_EXPECTED_1H',{'reason':'OTP 123456'}),
                       ('ALERT',{'requires_response':True,'phase':'OPERATOR','reason':'secret'}),
                       ('SECRETARY_REPLY',{'message_role':'CONTROL','private_notice':True,'reason':'secret'}),
                       ('SECRETARY_REPLY',{'message_role':'RESEARCH','account_id':'DU1234567','reason':'secret'})]:
            item=dict(id=1,kind=kind,incident_key='automatic:test',payload=p)
            view=render(item,CONFIG,self.now)
            self.assertEqual(view['chat_id'],-100)
            self.assertNotIn('123456',view['text']); self.assertNotIn('secret',view['text'])
        notice_batch(self.store,[123,124],'unresolved'); self.flush()
        bot=self.bot(); self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual([x[0] for x in bot.sends],[-100])

    def test_full_report_and_scoped_current_status_are_never_grouped_away(self):
        for kind in ['REPORT_BUNDLE','REPORT_SUPPLEMENT','CURRENT_RISK_STATUS']:
            with closing(self.store.connect()) as c,c:
                c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,?,?,'PENDING')",(kind,kind,json.dumps({'included_reports':['DAILY'],'png_artifacts':[{}]})))
        self.now+=1; prepare(self.store,CONFIG)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE status='PENDING'").fetchone()[0],3)
        report=dict(id=1,kind='REPORT_BUNDLE',incident_key='daily',payload={'included_reports':['DAILY']})
        self.assertEqual(decision(report,CONFIG)['audience'],'group')
        validate_config(CONFIG)
        with self.assertRaises(PermissionError):validate_config({**CONFIG,'account_report_policy':'private'})

    def test_policy_rollback_cannot_send_a_group_summary_to_private(self):
        self.source();self.flush();bot=self.bot()
        legacy={k:v for k,v in CONFIG.items() if k!='automatic_notification_policy'}
        result=asyncio.run(send_one(self.store,self.co,legacy,report_root=self.root,owned_bot=bot,clock=lambda:self.now))
        self.assertEqual(result,'PENDING');self.assertEqual(bot.sends,[])

    def test_more_than_one_batch_never_claims_an_unprojected_individual_fault(self):
        self.source('ANCHOR')
        with closing(self.store.connect()) as c,c:
            c.executemany("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'ALERT',?,'PENDING')",
                [('paper-safety:protection:'+str(i),json.dumps({'severity':'RED'})) for i in range(600)])
        prepare(self.store,CONFIG)
        self.assertIsNone(self.store.claim(automatic_grouped=True))
        self.now+=2; prepare(self.store,CONFIG)
        item=self.store.claim(automatic_grouped=True)
        self.assertEqual(item['kind'],'AUTOMATIC_STATUS')

    def test_destination_proof_cannot_race_a_recovery_against_new_fault(self):
        self.source(); self.flush(); bot=self.bot(); self.send(bot)
        self.now+=1; self.source(resolved=True,status='PROTECTED'); prepare(self.store,CONFIG)
        self.stabilize()
        recovery=self.summaries()[-1]
        original=bot.get_chat_administrators
        async def changed(*args,**kwargs):
            self.source(suffix='new-after-native-proof')
            return await original(*args,**kwargs)
        bot.get_chat_administrators=changed
        self.assertEqual(self.send(bot),'SUPPRESSED')
        self.assertEqual(len(bot.sends),1); self.assertEqual(bot.edits,[])
        self.assertEqual(get_item(self.store,recovery['id'])['status'],'SUPPRESSED')
        with closing(self.store.connect()) as c:
            self.assertIsNone(c.execute('SELECT 1 FROM notification_delivery WHERE notification_id=?',(recovery['id'],)).fetchone())

    def test_native_archive_origin_overrides_model_presentation_and_role(self):
        from reporting.agent_secretary import SecretaryArchive
        from reporting.secretary_queue import enqueue_reply
        archive=SecretaryArchive(self.root/'archive.sqlite3',clock=lambda:self.now)
        archive.append('authority','owner',origin='USER',kind='STANDING_AUTHORIZATION',payload={})
        for label,origin,kind in [('native','USER','CHAT_INSTRUCTION'),('auto','SYSTEM','AUTONOMOUS_INSTRUCTION')]:
            instruction=label+':instruction';run=label+':run'
            archive.append(instruction,'owner',origin=origin,kind=kind,payload={},parent='authority' if origin=='SYSTEM' else None)
            archive.reserve_run(run,instruction=instruction,model='fixture')
            archive.append(run+':result','owner',origin='MODEL',kind='RESULT',payload={'summary':'PRIVATE'},parent=instruction)
            archive.append(run+':presentation','owner',origin='MODEL',kind='PRESENTATION',payload={'native_owner_reply':origin!='USER'},parent=instruction)
            archive.finish_run(run,state='SUCCEEDED',result_event=run+':result')
            enqueue_reply(archive,self.store,run,'PRIVATE result',role='CHAT' if origin=='SYSTEM' else 'TASK')
            with closing(self.store.connect()) as c:
                ident=c.execute('SELECT id FROM notification_outbox WHERE incident_key=?',('secretary:'+run,)).fetchone()[0]
            item=get_item(self.store,ident)
            self.assertEqual(decision(item,CONFIG)['audience'],'owner' if origin=='USER' else 'group')

    def test_reserved_operation_source_is_retained_without_projection(self):
        ident=self.source()
        self.assertTrue(self.co.begin_operation('notification:outbox:'+str(ident),'delivery',{'outbox_id':ident}))
        self.assertEqual(self.flush(),0)
        self.assertEqual(get_item(self.store,ident)['status'],'PENDING')
        with closing(self.store.connect()) as c:
            self.assertIsNone(c.execute('SELECT 1 FROM automatic_notification_sources WHERE notification_id=?',(ident,)).fetchone())

    def test_aggregate_payload_identity_and_all_rendered_counts_are_bound(self):
        notice_batch(self.store,[123],'unresolved');self.flush()
        item=self.summaries()[-1];self.assertTrue(valid(self.store,item,self.now))
        for field,value in [('source_count','PRIVATE_REVIEW_SENTINEL'),('recovered_count','PRIVATE_RECOVERY_SENTINEL'),('source_count',501),('open_count',True),('phase','RECOVERED')]:
            changed={**item,'payload':{**item['payload'],field:value}}
            self.assertFalse(valid(self.store,changed,self.now))
            if field in ('source_count','recovered_count','open_count'):
                with self.assertRaises(PermissionError):render(changed,CONFIG,self.now)
        changed={**item,'generation':item['generation']+1};self.assertFalse(valid(self.store,changed,self.now))
        changed={**item,'generation':True};self.assertFalse(valid(self.store,changed,self.now))
        changed={**item,'id':True};self.assertFalse(valid(self.store,changed,self.now))
        changed={**item,'id':item['id']+1};self.assertFalse(valid(self.store,changed,self.now))
        changed={**item,'payload':{**item['payload'],'source_count':'PRIVATE_REVIEW_SENTINEL'}}
        with self.assertRaises(PermissionError):render(changed,CONFIG,self.now)
        # Even a matching rewritten outbox cannot change the independent registration.
        with closing(self.store.connect()) as c,c:
            changed={**item,'payload':{**item['payload'],'source_count':0,'source_notification_ids':[]}}
            c.execute('UPDATE notification_outbox SET payload=? WHERE id=?',(json.dumps(changed['payload'],sort_keys=True),item['id']))
        self.assertFalse(valid(self.store,changed,self.now))

    def test_recovery_clock_resets_on_stale_epoch_and_between_poll_faults(self):
        self.source();self.flush();self.send(self.bot())
        self.now+=1;self.source(resolved=True,status='PROTECTED');prepare(self.store,CONFIG)
        self.assertEqual(self.stabilize(30),0)
        # Fresh only at the end cannot establish a continuous healthy interval.
        self.now+=40;self.fresh();self.assertEqual(prepare(self.store,CONFIG),0)
        self.assertEqual(self.stabilize(30),0)
        self.now+=1;self.fresh(epoch='different-epoch');self.assertEqual(prepare(self.store,CONFIG),0)
        # A complete fault/recovery pair between polls must also reset the clock.
        self.now+=1;self.source(suffix='between-open')
        self.source(suffix='between-close',resolved=True,status='PROTECTED')
        self.fresh();self.assertEqual(prepare(self.store,CONFIG),0)
        self.assertEqual(self.stabilize(55),0)
        self.now+=5;self.fresh();self.assertEqual(prepare(self.store,CONFIG),1)

    def test_generic_module_red_escalation_is_timely_edit_without_protection_wording(self):
        self.store.ingest('yellow','module:feed',dict(scope='MODULE',severity='YELLOW'))
        self.flush();bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.now+=1;self.store.ingest('red','module:feed',dict(scope='MODULE',severity='RED'))
        self.assertEqual(self.flush(),1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
        self.assertIn('严重故障或风险升级',bot.edits[0]['text'])
        self.assertNotIn('保护覆盖缺口',bot.edits[0]['text'])

    def test_zero_wire_cancelled_recovery_can_reproject_after_new_stability(self):
        self.source();self.flush();bot=self.bot();self.send(bot)
        self.now+=1;self.source(resolved=True,status='PROTECTED');prepare(self.store,CONFIG);self.stabilize()
        old=self.summaries()[-1];original=bot.get_chat_administrators
        async def dirty(*args,**kwargs):
            with closing(self.store.connect()) as c,c:
                p=json.loads(c.execute('SELECT payload FROM paper_safety_state').fetchone()[0]);p['dirty']=True
                c.execute('UPDATE paper_safety_state SET payload=?',(json.dumps(p),))
            return await original(*args,**kwargs)
        bot.get_chat_administrators=dirty
        self.assertEqual(self.send(bot),'SUPPRESSED')
        bot.get_chat_administrators=original
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM automatic_projection_events WHERE notification_id=?',(old['id'],)).fetchone()[0],1)
            self.assertIsNone(c.execute('SELECT aggregate_id FROM automatic_notification_sources WHERE notification_id=?',(old['payload']['source_notification_ids'][0],)).fetchone()[0])
        self.assertEqual(self.stabilize(),1)
        new=self.summaries()[-1];self.assertNotEqual(new['id'],old['id'])
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
        self.assertEqual(get_item(self.store,old['id'])['status'],'SUPPRESSED')

    def test_historical_channel_test_is_retained_without_polluting_business_recovery(self):
        self.store.ingest('old-test','notification-channel-test:FEISHU-OLD',
            dict(scope='NOTIFICATION_CHANNEL_TEST',test_only=1,severity='RED'))
        self.store.ingest('real-fault','module:feed',dict(scope='MODULE',severity='RED'))
        self.flush();bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(self.summaries()[-1]['payload']['open_count'],1)
        self.now+=1;self.store.ingest('real-close','module:feed',dict(scope='MODULE',severity='GREEN'),resolved=True)
        prepare(self.store,CONFIG);self.now+=60;prepare(self.store,CONFIG)
        self.assertEqual(self.summaries()[-1]['payload']['phase'],'RECOVERED')
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT state FROM incidents WHERE incident_key='notification-channel-test:FEISHU-OLD'").fetchone()[0],'OPEN')
            self.assertEqual(c.execute("SELECT disposition FROM automatic_notification_sources WHERE family='test'").fetchone()[0],'test_evidence_retained')

    def test_partial_recovery_updates_same_card_and_does_not_oscillate(self):
        self.source('A');self.source('B');self.flush();bot=self.bot();self.send(bot)
        self.now+=1;self.source('A',resolved=True,status='PROTECTED');prepare(self.store,CONFIG)
        self.assertEqual(self.stabilize(),1)
        item=self.summaries()[-1]
        self.assertEqual(item['payload']['phase'],'RECOVERED');self.assertEqual(item['payload']['open_count'],1)
        self.assertEqual(item['payload']['recovered_count'],1);self.assertEqual(item['payload']['severity'],'RED')
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertIn('部分恢复汇总',bot.edits[-1]['text']);self.assertIn('仍待核验/处理 1',bot.edits[-1]['text'])
        count=len(self.summaries());self.assertEqual(self.stabilize(),0);self.assertEqual(len(self.summaries()),count)
        self.now+=1;self.source('B',resolved=True,status='PROTECTED');prepare(self.store,CONFIG)
        self.assertEqual(self.stabilize(),1);self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),2)
        self.assertEqual(self.summaries()[-1]['payload']['recovered_count'],2)
        self.assertEqual(self.summaries()[-1]['payload']['open_count'],0)

    def test_critical_escalation_during_partial_stability_does_not_consume_recovery(self):
        self.source('A');self.source('B');self.flush();bot=self.bot();self.send(bot)
        self.now+=1;recover=self.source('A',resolved=True,status='PROTECTED');prepare(self.store,CONFIG)
        self.stabilize(20)
        self.now+=1;self.source('B','gap',status='UNPROTECTED');self.assertEqual(self.flush(),1)
        self.assertEqual(self.summaries()[-1]['payload']['phase'],'FAULT')
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        with closing(self.store.connect()) as c:
            self.assertIsNone(c.execute('SELECT aggregate_id FROM automatic_notification_sources WHERE notification_id=?',(recover,)).fetchone()[0])
        self.assertEqual(self.stabilize(),1);self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertIn('部分恢复汇总',bot.edits[-1]['text'])
