import asyncio
from contextlib import closing
import json
import unittest
from unittest.mock import patch

import test_notification_disposition as disposition_fixtures
import test_notification_center as center_fixtures
from test_automatic_notifications import CONFIG
from reporting.automatic_notifications import prepare
from reporting.notification_center import get_item
from reporting.incident_telegram import send_one
from reporting.grouped_current import (GROUPED_ACTION,SOURCE_THREAD,SOURCE_MESSAGE,USER_TEXT,
    authorize_grouped_current,register_grouped_current,eligible_grouped_current_ids,grouped_current_valid)
from reporting.notification_disposition import validate_before_wire


class GroupedCurrentTests(unittest.TestCase):
    save_state=disposition_fixtures.DispositionTests.save_state
    archive=disposition_fixtures.DispositionTests.archive

    def setUp(self):
        disposition_fixtures.DispositionTests.setUp(self)
        self.archive();prepare(self.store,CONFIG)
        self.group_auth=dict(action=GROUPED_ACTION,origin='USER',source_thread=SOURCE_THREAD,
            source_message=SOURCE_MESSAGE,user_text=USER_TEXT,interpretation='New post-cutover stable current group facts only; keep exact three unknown, never replay.')
        with closing(self.store.connect()) as c,c:
            c.execute("INSERT INTO incidents VALUES ('paper-safety:protection:PFE',171,'RESOLVED',1,2)")

    def authorize(self):
        return authorize_grouped_current(self.store,'grouped-owner','owner-scope',self.group_auth)

    def fresh(self):
        self.state.update(last_server_reply=self.now,reconciled_at=self.now)
        self.save_state()

    def bot(self):return center_fixtures.NotificationCenterTests.bot(self)

    def send(self,bot):
        return asyncio.run(send_one(self.store,self.co,CONFIG,report_root=self.root,owned_bot=bot,clock=lambda:self.now))

    def open(self):
        self.now+=1
        self.store.ingest('new-PFE-fault','paper-safety:protection:PFE',dict(severity='RED',protection_status='PROTECTION_UNKNOWN'))
        prepare(self.store,CONFIG);self.now+=2;prepare(self.store,CONFIG)
        bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        return bot

    def recovery(self):
        self.now+=1;self.fresh()
        self.store.ingest('new-PFE-recovery','paper-safety:protection:PFE',dict(severity='GREEN',protection_status='PROTECTED'),resolved=True)
        prepare(self.store,CONFIG)
        for _ in range(13):
            self.now+=5;self.fresh();prepare(self.store,CONFIG)
        with closing(self.store.connect()) as c:
            ident=c.execute("SELECT max(id) FROM notification_outbox WHERE kind='AUTOMATIC_STATUS'").fetchone()[0]
        item=get_item(self.store,ident);self.assertEqual(item['payload']['phase'],'RECOVERED')
        return item

    def test_exact_operator_scope_allows_only_new_stable_registered_recovery(self):
        self.authorize();self.authorize();bot=self.open();item=self.recovery()
        with closing(self.store.connect()) as c:
            self.assertEqual(eligible_grouped_current_ids(self.store,c,self.now),(item['id'],))
            self.assertTrue(grouped_current_valid(self.store,c,item,self.now))
            self.assertTrue(item['payload']['recovery_members'])
            self.assertEqual(c.execute('SELECT count(*) FROM notification_grouped_current').fetchone()[0],1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1);self.assertEqual(len(bot.edits),1)
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE id IN (1270,1271,1272) AND status='STARTED'").fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_retry_authorizations').fetchone()[0],0)

    def test_no_new_scope_keeps_original_guard_even_after_exact_legacy_archive(self):
        self.open();self.recovery()
        self.assertIsNone(self.store.claim(automatic_grouped=True))

    def test_wrong_user_provenance_cutover_and_original_evidence_fail_closed(self):
        for change in ({'source_message':'different'},{'source_thread':'model'},{'origin':'MODEL'},{'user_text':'please replay'}):
            with self.assertRaises(PermissionError):authorize_grouped_current(self.store,'bad','owner-scope',{**self.group_auth,**change})
        self.authorize();self.open();item=self.recovery()
        with closing(self.store.connect()) as c,c:
            self.assertTrue(grouped_current_valid(self.store,c,item,self.now))
            c.execute("UPDATE incident_cursors SET payload=? WHERE source='automatic-policy:grouped-v1'",(json.dumps({'cutover_id':1,'installed_at':1000}),))
            self.assertFalse(grouped_current_valid(self.store,c,item,self.now))
        self.assertIsNone(self.store.claim(automatic_grouped=True))

    def test_other_unknown_and_late_old_receipt_are_not_retired(self):
        self.authorize();self.open();item=self.recovery()
        with closing(self.store.connect()) as c,c:
            c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES('paper-safety:protection:OTHER',1,'ALERT','{}','UNKNOWN')")
            self.assertFalse(grouped_current_valid(self.store,c,item,self.now))
        self.assertIsNone(self.store.claim(automatic_grouped=True))
        with closing(self.store.connect()) as c,c:
            c.execute("DELETE FROM notification_outbox WHERE incident_key='paper-safety:protection:OTHER'")
            c.execute('INSERT INTO notification_receipts VALUES (1271,?)',(json.dumps({'new':'positive evidence'}),))
        self.assertIsNone(self.store.claim(automatic_grouped=True))
        with self.assertRaises(PermissionError):validate_before_wire(self.store,item,self.now)

    def test_epoch_latch_and_source_changes_invalidate_claim_and_wire(self):
        self.authorize();self.open();item=self.recovery()
        with patch('reporting.automatic_notifications.persistence_clear',return_value=False):
            self.assertIsNone(self.store.claim(automatic_grouped=True))
            with self.assertRaises(PermissionError):validate_before_wire(self.store,item,self.now)
        self.state['epoch']='new-epoch';self.save_state()
        self.assertIsNone(self.store.claim(automatic_grouped=True))
        self.state['epoch']='native-epoch';self.save_state()
        source=item['payload']['source_notification_ids'][0]
        with closing(self.store.connect()) as c,c:
            c.execute("UPDATE notification_outbox SET payload='{}' WHERE id=?",(source,))
        self.assertIsNone(self.store.claim(automatic_grouped=True))

    def test_old_source_or_member_cannot_be_registered_as_a_new_recovery(self):
        self.authorize();self.open();item=self.recovery()
        with closing(self.store.connect()) as c,c:
            self.assertTrue(grouped_current_valid(self.store,c,item,self.now))
            p={**item['payload'],'recovery_members':[{'notification_id':1271}]}
            changed={**item,'payload':p}
            with self.assertRaises(PermissionError):register_grouped_current(self.store,c,changed,'grouped-owner')

    def test_unknown_aggregate_remains_a_barrier_to_future_registered_versions(self):
        self.authorize();self.open();item=self.recovery();claimed=self.store.claim(automatic_grouped=True)
        self.assertEqual(claimed['id'],item['id'])
        self.store.delivery_started(item['id'],self.now);self.store.finish(item['id'],'UNKNOWN')
        self.now+=5;self.fresh();prepare(self.store,CONFIG)
        self.assertIsNone(self.store.claim(automatic_grouped=True))
        self.assertEqual(get_item(self.store,item['id'])['status'],'UNKNOWN')

    def test_current_fallback_also_rejects_shared_local_persistence_fault(self):
        from reporting.notification_disposition import queue_current
        with patch('reporting.automatic_notifications.persistence_clear',return_value=False):
            with self.assertRaises(PermissionError):queue_current(self.store,'owner-scope')

    def test_registered_partial_recovery_does_not_clear_real_remaining_fault(self):
        self.authorize();bot=self.open()
        self.now+=1;self.store.ingest('remaining','paper-safety:collision',dict(severity='RED'))
        prepare(self.store,CONFIG);self.now+=2;prepare(self.store,CONFIG);self.send(bot)
        item=self.recovery()
        self.assertEqual(item['payload']['phase'],'RECOVERED')
        self.assertEqual(item['payload']['open_count'],1)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertIn('部分恢复汇总',bot.edits[-1]['text'])
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute("SELECT state FROM incidents WHERE incident_key='paper-safety:collision'").fetchone()[0],'OPEN')
