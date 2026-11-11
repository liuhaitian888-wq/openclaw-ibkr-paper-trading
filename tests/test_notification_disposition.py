import asyncio
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.notification_center import get_item,render
from reporting.notification_disposition import LEGACY,ACTION,archive_dependencies,queue_current,validate_before_wire,sha
from reporting.incident_telegram import send_one
import test_notification_reconciliation as reconciliation_fixtures


class DispositionTests(unittest.TestCase):
    def setUp(self):
        guard=patch('reporting.automatic_notifications.persistence_clear',return_value=True)
        guard.start();self.addCleanup(guard.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=1000;self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now);self.co=RecoveryCoordinator(self.store.path)
        self.expected={};self.auth=dict(action=ACTION,origin='USER',source_thread='risk',source_message='native-owner-instruction',user_text='Investigate three and resolve current delivery block',interpretation='Keep outcome unknown; no old send; fresh current status only')
        with closing(self.store.connect()) as c,c:
            for ident,(key,generation) in LEGACY.items():
                payload=json.dumps({'reason':'old private facts','queued_at':1})
                self.expected[ident]=sha(payload)
                c.execute('INSERT INTO notification_outbox VALUES(?,?,?,?,?,?)',(ident,key,generation,'ALERT',payload,'STARTED'))
            c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
        self.state=dict(epoch='native-epoch',identity=True,connected=True,upstream_connected=True,dirty=False,
            last_server_reply=1000,reconciled_at=995,ends=['orders','positions','executions','completed_orders'],
            positions={'PRIVATE_SYMBOL':0},contracts={},orders={})
        self.state['positions']={'PRIVATE_SYMBOL':2};self.state['contracts']={'PRIVATE_SYMBOL':dict(currency='USD',sec_type='STK',con_id=1)}
        self.state['orders']={'1':dict(account='DUQ503649',symbol='PRIVATE_SYMBOL',side='SELL',order_type='STP',status='Submitted',
            transmit=True,parent_id=0,perm_id=1,remaining=2,aux_price=10,currency='USD',sec_type='STK',con_id=1)}
        self.save_state()

    def save_state(self):
        with closing(self.store.connect()) as c,c:c.execute('INSERT OR REPLACE INTO paper_safety_state VALUES(1,?)',(json.dumps(self.state),))
    def archive(self):return archive_dependencies(self.store,'owner-scope',self.auth,self.expected)

    def test_exact_archive_preserves_original_bytes_and_old_pending_symbol_queue(self):
        with closing(self.store.connect()) as c,c:
            before=list(c.execute('SELECT * FROM notification_outbox'))
            c.execute("INSERT INTO notification_outbox VALUES(1300,'paper-safety:protection:NIO',8,'ALERT','{}','PENDING')")
            c.execute("INSERT INTO notification_outbox VALUES(1301,'paper-safety:protection-recovery-batch:old',1,'RECOVERY',?,'PENDING')",(json.dumps({'scope':'PAPER_SAFETY','recovery_digest_version':1}),))
        self.archive();self.archive()
        with self.assertRaises(PermissionError):archive_dependencies(self.store,'owner-scope',self.auth,{**self.expected,1270:'wrong'})
        with closing(self.store.connect()) as c:
            self.assertEqual(list(c.execute('SELECT * FROM notification_outbox WHERE id IN (1270,1271,1272)')),before)
            self.assertEqual(c.execute('SELECT status FROM notification_outbox WHERE id=1300').fetchone()[0],'PENDING')
            self.assertEqual(c.execute('SELECT status FROM notification_outbox WHERE id=1301').fetchone()[0],'SUPERSEDED')
            self.assertEqual(c.execute('SELECT count(*) FROM notification_dependency_dispositions').fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_retry_authorizations').fetchone()[0],0)

    def test_bad_scope_hash_and_new_positive_operation_are_rejected(self):
        for expected in ({953:'x'},dict(self.expected,**{})|{1270:'bad'}):
            with self.assertRaises(PermissionError):archive_dependencies(self.store,'bad',self.auth,expected)
        self.co.begin_operation('notification:outbox:1270','delivery',{'outbox_id':1270})
        with self.assertRaises(PermissionError):self.archive()

    def test_current_report_is_fresh_bound_group_only_and_does_not_retry_or_mirror(self):
        self.archive();ident=queue_current(self.store,'owner-scope');self.assertEqual(ident,queue_current(self.store,'owner-scope'))
        from test_notification_center import CFG
        cfg={**CFG,'automatic_updates_to_group':True};view=render(get_item(self.store,ident),cfg,1000)
        self.assertEqual(view['chat_id'],-100);self.assertNotIn('PRIVATE_SYMBOL',view['text']);self.assertIn('旧三条投递结果未知',view['text'])
        bot=reconciliation_fixtures.ReconciliationTests.bot(self)
        self.assertEqual(asyncio.run(send_one(self.store,self.co,cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now)),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(bot.sends[0][0],-100)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE kind='SECRETARY_REPLY'").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_retry_authorizations').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_receipts WHERE notification_id IN (1270,1271,1272)').fetchone()[0],0)

    def test_stale_dirty_changed_epoch_and_changed_original_all_fail_closed(self):
        self.archive();ident=queue_current(self.store,'owner-scope');item=get_item(self.store,ident)
        self.assertEqual(item['payload']['source_observed_at'],995)
        for changes in ({'dirty':True},{'epoch':'other'},{'last_server_reply':900},{'orders':{}}):
            original=dict(self.state);self.state.update(changes);self.save_state()
            with self.assertRaises(PermissionError):validate_before_wire(self.store,item,self.now)
            self.state=original;self.save_state()
        with self.assertRaises(PermissionError):validate_before_wire(self.store,item,1031)
        with closing(self.store.connect()) as c,c:c.execute("UPDATE notification_outbox SET payload='{}' WHERE id=1270")
        with self.assertRaises(PermissionError):validate_before_wire(self.store,item,self.now)

    def test_other_unknown_protection_blocks_but_report_unknown_is_untouched(self):
        self.archive();ident=queue_current(self.store,'owner-scope')
        with closing(self.store.connect()) as c,c:
            c.execute("INSERT INTO notification_outbox VALUES(953,'other',1,'SECRETARY_REPLY','{}','UNKNOWN')")
            c.execute("INSERT INTO notification_outbox VALUES(1094,'financial-reports:old',1,'REPORT_BUNDLE','{}','UNKNOWN')")
            c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES('paper-safety:protection:OTHER',1,'ALERT','{}','UNKNOWN')")
        self.assertIsNone(self.store.claim())
        with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT status FROM notification_outbox WHERE id=1094').fetchone()[0],'UNKNOWN')

    def test_tampered_current_payload_and_wrong_legacy_generation_are_not_accepted(self):
        with closing(self.store.connect()) as c,c:c.execute('UPDATE notification_outbox SET generation=8 WHERE id=1270')
        with self.assertRaises(PermissionError):self.archive()
        with closing(self.store.connect()) as c,c:c.execute('UPDATE notification_outbox SET generation=7 WHERE id=1270')
        self.archive();ident=queue_current(self.store,'owner-scope')
        with closing(self.store.connect()) as c,c:
            c.execute("UPDATE notification_outbox SET payload=json_set(payload,'$.recovered_count',99) WHERE id=?",(ident,))
        self.assertIsNone(self.store.claim())

    def test_old_digest_with_receipt_and_unrelated_flagged_event_are_not_superseded(self):
        p=json.dumps({'scope':'PAPER_SAFETY','recovery_digest_version':1})
        with closing(self.store.connect()) as c,c:
            c.execute("INSERT INTO notification_outbox VALUES(1301,'paper-safety:protection-recovery-batch:receipt',1,'RECOVERY',?,'PENDING')",(p,))
            c.execute("INSERT INTO notification_receipts VALUES(1301,'{}')")
            c.execute("INSERT INTO notification_outbox VALUES(1302,'unrelated',1,'ALERT',?,'PENDING')",(p,))
        self.archive()
        with closing(self.store.connect()) as c:
            self.assertEqual(list(c.execute('SELECT status FROM notification_outbox WHERE id IN (1301,1302)')),[('PENDING',),('PENDING',)])

    def test_flat_state_does_not_hide_active_external_order_exposure(self):
        self.state['positions']={};self.save_state();self.archive()
        item=get_item(self.store,queue_current(self.store,'owner-scope'))
        self.assertEqual(item['payload']['recovered_count'],0)
        self.assertEqual(item['payload']['unresolved_count'],1)

    def test_changed_authorization_record_invalidates_scope(self):
        self.archive();ident=queue_current(self.store,'owner-scope')
        with closing(self.store.connect()) as c,c:c.execute("UPDATE notification_disposition_scopes SET authorization='{}'")
        with self.assertRaises(PermissionError):validate_before_wire(self.store,get_item(self.store,ident),1000)

    def test_state_invalidated_during_native_destination_check_never_enters_wire(self):
        self.archive();ident=queue_current(self.store,'owner-scope')
        from test_notification_center import CFG
        cfg={**CFG,'automatic_updates_to_group':True}
        bot=reconciliation_fixtures.ReconciliationTests.bot(self)
        prior=bot.get_chat_administrators
        async def invalidate(*args,**kwargs):
            self.state['dirty']=True;self.save_state()
            return await prior(*args,**kwargs)
        bot.get_chat_administrators=invalidate
        result=asyncio.run(send_one(self.store,self.co,cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now))
        self.assertEqual(result,'PENDING');self.assertEqual(bot.sends,[])
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM operation_attempts').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_delivery').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM notification_attempt_events WHERE stage='PREFLIGHT_FAILED'").fetchone()[0],1)
        self.assertEqual(get_item(self.store,ident)['status'],'PENDING')

    def test_current_unknown_survives_recovery_without_retry_or_private_notice(self):
        self.archive()
        from test_notification_center import CFG
        from reporting.notification_reconciliation import recover
        cfg={**CFG,'automatic_updates_to_group':True}
        bot=reconciliation_fixtures.ReconciliationTests.bot(self,fail=TimeoutError('ambiguous'))
        # Existing legacy review notices have their own unchanged lifecycle.
        asyncio.run(recover(self.store,self.co,cfg,bot,self.root))
        with closing(self.store.connect()) as c:
            baseline=c.execute("SELECT count(*) FROM notification_outbox WHERE kind='SECRETARY_REPLY'").fetchone()[0]
        ident=queue_current(self.store,'owner-scope')
        result=asyncio.run(send_one(self.store,self.co,cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now))
        self.assertEqual(result,'UNKNOWN')
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='Never replay uncertain transport')
        asyncio.run(recover(self.store,self.co,cfg,bot,self.root))
        self.assertEqual(get_item(self.store,ident)['status'],'UNKNOWN');self.assertEqual(len(bot.sends),1)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM notification_retry_authorizations').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE kind='SECRETARY_REPLY'").fetchone()[0],baseline)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_review_notices WHERE notification_id=?',(ident,)).fetchone()[0],0)

    def test_explicit_zero_wire_refresh_retains_versions_and_one_wire_scope(self):
        self.archive();old=queue_current(self.store,'owner-scope');original=get_item(self.store,old)['payload']
        from test_notification_center import CFG
        cfg={**CFG,'automatic_updates_to_group':True};bot=reconciliation_fixtures.ReconciliationTests.bot(self)
        self.now=1031
        self.assertEqual(asyncio.run(send_one(self.store,self.co,cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now)),'PENDING')
        self.assertEqual(bot.sends,[])
        self.assertEqual(queue_current(self.store,'owner-scope'),old)
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='Stale source still denied')
        self.state.update(last_server_reply=self.now,reconciled_at=self.now);self.save_state()
        new=queue_current(self.store,'owner-scope',refresh_unsent_reason='Operator confirmed terminal preflight only; refresh actual source')
        self.assertNotEqual(new,old);self.assertEqual(get_item(self.store,old)['status'],'SUPERSEDED')
        self.assertEqual(get_item(self.store,old)['payload'],original)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM notification_current_status').fetchone()[0],2)
            self.assertEqual(c.execute("SELECT count(*) FROM notification_disposition_events WHERE action='CURRENT_STATUS_ZERO_WIRE_REFRESH'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_attempts WHERE notification_id=?',(old,)).fetchone()[0],1)
        self.store.delivery_receipt(old,{'transport':'unexpected_new_evidence'})
        with self.assertRaises(PermissionError):validate_before_wire(self.store,get_item(self.store,new),self.now)
        with closing(self.store.connect()) as c,c:c.execute('DELETE FROM notification_receipts WHERE notification_id=?',(old,))
        with closing(self.store.connect()) as c:
            aid=c.execute('SELECT id FROM notification_attempts WHERE notification_id=?',(old,)).fetchone()[0]
        faults=[
            ("INSERT INTO operation_attempts VALUES(?,'delivery','STARTED','{}')",('notification:outbox:'+str(old),),
             'DELETE FROM operation_attempts WHERE identity=?',('notification:outbox:'+str(old),)),
            ("INSERT INTO notification_attempt_events(attempt_id,observed_at,stage,evidence) VALUES(?,1031,'WIRE_START','{}')",(aid,),
             "DELETE FROM notification_attempt_events WHERE attempt_id=? AND stage='WIRE_START'",(aid,)),
            ("UPDATE notification_outbox SET status='UNKNOWN' WHERE id=?",(old,),
             "UPDATE notification_outbox SET status='SUPERSEDED' WHERE id=?",(old,)),
        ]
        for inject,args,restore,undo_args in faults:
            with self.subTest(late_evidence=inject):
                with closing(self.store.connect()) as c,c:c.execute(inject,args)
                try:
                    self.assertIsNone(self.store.claim())
                    with self.assertRaises(PermissionError):validate_before_wire(self.store,get_item(self.store,new),self.now)
                finally:
                    with closing(self.store.connect()) as c,c:c.execute(restore,undo_args)
        validate_before_wire(self.store,get_item(self.store,new),self.now)
        self.assertEqual(asyncio.run(send_one(self.store,self.co,cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now)),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1)
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='Accepted cannot refresh')
        with self.assertRaises(PermissionError):validate_before_wire(self.store,get_item(self.store,old),self.now)

    def test_refresh_requires_positive_terminal_evidence_and_no_reservation(self):
        self.archive();ident=queue_current(self.store,'owner-scope')
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='No positive failed attempt')
        item=self.store.claim()
        self.assertEqual(item['id'],ident)
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='Claim still in flight')
        from reporting.notification_reconciliation import begin_attempt,event
        aid=begin_attempt(self.store,item);event(self.store,aid,'PREFLIGHT_FAILED',{'wire_started':False})
        self.store.defer_unsent(ident)
        self.co.begin_operation('notification:outbox:'+str(ident),'delivery',{'outbox_id':ident})
        with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope',refresh_unsent_reason='Operation reservation blocks refresh')

    def test_unpublished_old_registry_schema_is_not_silently_activated(self):
        from reporting.notification_disposition import initialize
        with closing(self.store.connect()) as c,c:
            c.execute('DROP TABLE notification_current_status')
            c.execute('CREATE TABLE notification_current_status(scope_id TEXT PRIMARY KEY,notification_id INTEGER UNIQUE,payload TEXT,state_sha256 TEXT,observed_at REAL,expires_at REAL)')
            c.execute("INSERT INTO notification_current_status VALUES('old',1300,'original','hash',1,2)")
        with self.assertRaises(PermissionError):initialize(self.store)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT payload FROM notification_current_status').fetchone()[0],'original')
