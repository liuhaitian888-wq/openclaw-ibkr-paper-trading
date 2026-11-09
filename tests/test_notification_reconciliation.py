import asyncio
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace as V

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.incident_telegram import send_one
from reporting.notification_artifacts import freeze
from reporting.notification_center import get_item
from reporting.notification_reconciliation import (assess,authorize_retry,begin_attempt,event,recover,inspect)
from test_notification_center import CFG


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.now=1000
        self.store=IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)
        self.co=RecoveryCoordinator(self.store.path,clock=lambda:self.now)
        self.cfg={**CFG,'automatic_updates_to_group':True,'account_report_policy':'shared_group','_report_root':str(self.root)}
        self.sequence=0

    def add(self,*,status='PENDING',**p):
        payload={'queued_at':999,'reason':'fixture','message_role':'TASK',**p}
        self.sequence+=1
        with closing(self.store.connect()) as c,c:
            cur=c.execute("INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES(?,1,'SECRETARY_REPLY',?,?)",
                ('case:'+str(self.sequence),json.dumps(payload),status))
            return cur.lastrowid

    def stage(self,ident,stage,evidence=None):
        aid=begin_attempt(self.store,get_item(self.store,ident));event(self.store,aid,stage,evidence)
        return aid

    def bot(self,*,fail=None):
        class Bot:
            sends=[]
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def get_me(self,**k):return V(id=9,username=CFG['bot_username'])
            async def get_chat(self,cid,**k):return V(id=cid,title='der' if cid<0 else None,type='supergroup' if cid<0 else 'private')
            async def get_chat_member_count(self,*a,**k):return 4
            async def get_chat_administrators(self,*a,**k):return [V(status='creator',user=V(id=42))]
            async def send_message(self,cid,**k):
                self.sends.append((cid,k))
                if fail:raise fail
                return V(chat=V(id=cid),message_id=77,date=datetime.now(timezone.utc))
        return Bot()

    def send(self,bot):return asyncio.run(send_one(self.store,self.co,self.cfg,report_root=self.root,bot_factory=lambda **k:bot,clock=lambda:self.now))

    def review(self,ident):return assess(self.store,ident)

    def retry(self,review,**changes):return authorize_retry(self.store,review['review_id'],review['evidence_fingerprint'],{**self.cfg,**changes},dependency_verified=True)

    def test_unknown_and_crash_without_receipt_never_prove_unsent(self):
        for status in ('UNKNOWN','STARTED'):
            ident=self.add(status=status,status_marker=status)
            self.stage(ident,'UNKNOWN')
            result=self.review(ident)
            self.assertEqual(result['decision'],'UNRESOLVED')
            with self.assertRaises(PermissionError):self.retry(result)
            self.assertEqual(get_item(self.store,ident)['status'],status)

    def test_malformed_receipt_stays_unresolved(self):
        ident=self.add(status='UNKNOWN')
        self.store.delivery_receipt(ident,{'transport':'telegram','chat_id':-100,'message_ids':[True],'server_dates':['bad']})
        self.assertEqual(self.review(ident)['decision'],'UNRESOLVED')

    def test_conflicting_receipts_and_projection_failure_never_resend(self):
        ident=self.add();bot=self.bot()
        with patch.object(self.store,'delivery_receipt',side_effect=OSError('projection failed')):
            self.assertEqual(self.send(bot),'UNKNOWN')
        self.assertEqual(self.review(ident)['decision'],'ALREADY_ACCEPTED')
        asyncio.run(recover(self.store,self.co,self.cfg,bot,self.root))
        self.assertEqual(get_item(self.store,ident)['status'],'TELEGRAM_ACCEPTED')
        self.assertEqual(len(bot.sends),1)
        with closing(self.store.connect()) as c,c:
            receipt=json.loads(c.execute('SELECT payload FROM notification_receipts WHERE notification_id=?',(ident,)).fetchone()[0])
            receipt['message_ids']=[999]
            c.execute('UPDATE notification_receipts SET payload=? WHERE notification_id=?',(json.dumps(receipt),ident))
        self.assertEqual(self.review(ident)['decision'],'UNRESOLVED')

    def test_accepted_evidence_repairs_unknown_without_transport(self):
        ident=self.add(status='UNKNOWN')
        aid=self.stage(ident,'WIRE_START',{'chat_id':42,'message_count':1,'action':'SEND'})
        receipt=dict(transport='telegram',chat_id=42,message_ids=[77],server_dates=['2026-11-10T01:00:00+00:00'])
        event(self.store,aid,'ACCEPTED',{'receipt':receipt})
        bot=self.bot()
        asyncio.run(recover(self.store,self.co,self.cfg,bot,self.root))
        self.assertEqual(get_item(self.store,ident)['status'],'TELEGRAM_ACCEPTED')
        self.assertEqual(bot.sends,[])
        self.assertEqual(self.review(ident)['decision'],'ALREADY_ACCEPTED')

    def test_preflight_failure_one_retry_and_original_evidence_unchanged(self):
        ident=self.add(status='NOT_SENT_EXHAUSTED')
        self.stage(ident,'PREFLIGHT_FAILED',{'error_class':'PermissionError'})
        review=self.review(ident);self.assertEqual(review['decision'],'PROVEN_UNSENT')
        retry=self.retry(review)
        self.assertIsInstance(retry,int);self.assertIsNone(self.retry(review))
        self.assertEqual(get_item(self.store,ident)['status'],'NOT_SENT_EXHAUSTED')
        self.assertEqual(get_item(self.store,retry)['payload']['retry_of'],ident)

    def test_changed_evidence_or_envelope_refuses_authorization(self):
        ident=self.add(status='NOT_SENT_EXHAUSTED');aid=self.stage(ident,'PREFLIGHT_FAILED')
        review=self.review(ident);event(self.store,aid,'BLOCKED')
        with self.assertRaises(PermissionError):self.retry(review)
        ident=self.add(status='NOT_SENT_EXHAUSTED',different=True);self.stage(ident,'PREFLIGHT_FAILED')
        with closing(self.store.connect()) as c,c:c.execute("UPDATE notification_outbox SET payload=json_set(payload,'$.reason','changed') WHERE id=?",(ident,))
        with self.assertRaises(PermissionError):self.retry(self.review(ident))

    def test_expiry_missing_recovery_and_retry_budget_cannot_be_bypassed(self):
        ident=self.add(status='NOT_SENT_EXHAUSTED',expires_at=999);self.stage(ident,'PREFLIGHT_FAILED')
        review=self.review(ident)
        with self.assertRaises(PermissionError):self.retry(review)
        with self.assertRaises(PermissionError):authorize_retry(self.store,review['review_id'],review['evidence_fingerprint'],self.cfg,dependency_verified=False)

    def test_timeout_is_durable_append_only_and_deduped_private_notice(self):
        ident=self.add();bot=self.bot(fail=TimeoutError('https://secret-url-must-not-be-saved.invalid'))
        self.assertEqual(self.send(bot),'UNKNOWN')
        self.assertEqual(self.review(ident)['decision'],'UNRESOLVED')
        for _ in range(2):asyncio.run(recover(self.store,self.co,self.cfg,bot,self.root))
        with closing(self.store.connect()) as c:
            evidence=' '.join(x[0] for x in c.execute('SELECT evidence FROM notification_attempt_events'))
            self.assertNotIn('secret-url',evidence)
            self.assertIn('TimeoutError',evidence)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_review_notices').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_reviews').fetchone()[0],1)
        self.assertEqual(len(bot.sends),1)

    def test_typed_rejection_allows_one_linked_send_with_explanation_and_private_notice(self):
        from telegram.error import RetryAfter
        ident=self.add(fixed_public_status=True);bot=self.bot(fail=RetryAfter(1))
        self.assertEqual(self.send(bot),'UNKNOWN')
        review=self.review(ident);self.assertEqual(review['decision'],'PROVEN_UNSENT')
        self.now+=2
        good=self.bot();asyncio.run(recover(self.store,self.co,self.cfg,good,self.root))
        with closing(self.store.connect()) as c:retry=c.execute('SELECT retry_id FROM notification_retry_authorizations').fetchone()[0]
        self.assertEqual(self.send(good),'TELEGRAM_ACCEPTED')
        self.assertIn('补发｜',good.sends[0][1]['text'])
        self.assertIn('#'+str(ident),good.sends[0][1]['text'])
        asyncio.run(recover(self.store,self.co,self.cfg,good,self.root))
        self.assertEqual(self.send(good),'TELEGRAM_ACCEPTED')
        self.assertEqual(good.sends[-1][0],42)
        self.assertEqual(get_item(self.store,ident)['status'],'UNKNOWN')
        self.assertEqual(get_item(self.store,retry)['status'],'TELEGRAM_ACCEPTED')

    def test_changed_original_target_and_corrupted_artifact_refuse_retry(self):
        ident=self.add(status='UNKNOWN',fixed_public_status=True)
        aid=self.stage(ident,'WIRE_START',{'chat_id':42,'message_count':1,'action':'SEND'})
        event(self.store,aid,'REJECTED')
        with self.assertRaises(PermissionError):self.retry(self.review(ident))
        # File snapshot hash validation is independent of the mutable original.
        png=self.root/'original.png';data=b'\x89PNG\r\n\x1a\nfixture';png.write_bytes(data)
        snap=freeze(self.root,png,hashlib.sha256(data).hexdigest());png.write_bytes(b'new preview')
        self.assertEqual(Path(snap['path']).read_bytes(),data)
        self.assertEqual(Path(snap['path']).stat().st_mode&0o777,0o400)
        self.assertEqual(freeze(self.root,Path(snap['path']),snap['sha256'])['sha256'],snap['sha256'])
        Path(snap['path']).chmod(0o600);Path(snap['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):freeze(self.root,png,snap['sha256'])

    def test_model_evidence_tool_is_read_only_and_not_a_retry_tool(self):
        ident=self.add(status='UNKNOWN');self.stage(ident,'UNKNOWN')
        with closing(self.store.connect()) as c:before=c.total_changes
        result=inspect(self.root,ident);self.assertEqual(result['decision'],'UNRESOLVED')
        with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_reviews').fetchone()[0],0)
        from reporting.secretary_read import tool
        with self.assertRaises(PermissionError):tool(self.root,{'name':'authorize_retry','notification_id':ident})

    def test_enqueue_freezes_selected_bytes_before_builder_overwrites_latest(self):
        from reporting.report_schedule import enqueue_reports,BJ
        now=datetime(2026,11,5,9,tzinfo=BJ);self.now=now.timestamp()
        directory=self.root/'2026-11-05';directory.mkdir()
        png=directory/'DAILY.png';data=b'\x89PNG\r\n\x1a\nfrozen-report';png.write_bytes(data)
        manifest=dict(generated_at=now.isoformat(),source_snapshot_at=now.isoformat(),report_date='2026-11-05',
            report_type='DAILY',account_id='DU123',environment='PAPER',source_validated=True,image_path=str(png),
            image_sha256=hashlib.sha256(data).hexdigest(),trading_period=dict(start_date='2026-11-04',end_date_exclusive='2026-11-05'))
        (directory/'DAILY.json').write_text(json.dumps(manifest))
        self.assertEqual(enqueue_reports(self.store,self.root,'DU123',now,transport='telegram'),'REPORT_BUNDLE')
        item=get_item(self.store,1);art=item['payload']['png_artifacts'][0]
        self.assertIn('/immutable/',art['path']);self.assertNotEqual(art['path'],str(png))
        png.write_bytes(b'preview changed');(directory/'DAILY.json').write_text('{}')
        from reporting.incident_telegram import report_bytes
        self.assertEqual(report_bytes(item,self.root)[0][1],data)
        self.assertEqual(json.loads(Path(item['payload']['report_manifests'][0]['path']).read_text()),manifest)
        self.assertEqual(item['payload']['expires_at'],now.timestamp()+600)

    def test_rotation_reviews_all_legacy_crashes_without_manufacturing_unsent_proof(self):
        ids=[self.add(status='STARTED',marker=i) for i in range(4)]
        bot=self.bot()
        for _ in range(3):asyncio.run(recover(self.store,self.co,self.cfg,bot,self.root,limit=2))
        with closing(self.store.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM notification_reviews').fetchone()[0],4)
            self.assertEqual(c.execute('SELECT count(*) FROM notification_retry_authorizations').fetchone()[0],0)
        self.assertEqual(bot.sends,[])

    def test_recovery_digest_public_card_has_counts_only(self):
        ident=self.add(recovery_digest_version=1,recovered_count=7,unresolved_count=1,recovery_members=[{'symbol':'PRIVATE_SYMBOL','notification_id':1}])
        with closing(self.store.connect()) as c,c:c.execute("UPDATE notification_outbox SET kind='RECOVERY',incident_key='paper-safety:protection-recovery-batch:fixture' WHERE id=?",(ident,))
        bot=self.bot();self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED')
        self.assertEqual(bot.sends[0][0],42)
        self.assertEqual(self.send(bot),'TELEGRAM_ACCEPTED');text=bot.sends[1][1]['text']
        self.assertEqual(bot.sends[1][0],-100);self.assertIn('恢复 7',text);self.assertIn('待核验 1',text)
        self.assertNotIn('PRIVATE_SYMBOL',text)

    def test_existing_backup_owner_preserves_frozen_report_bytes_and_detects_corruption(self):
        from reporting.notification_artifacts import backup
        root=self.root/'reports/financial';root.mkdir(parents=True)
        png=root/'preview.png';data=b'\x89PNG\r\n\x1a\nfrozen';png.write_bytes(data)
        art=freeze(root,png,hashlib.sha256(data).hexdigest())
        target=self.root/'backup';result=backup(self.root,target)
        self.assertEqual(result['status'],'BACKED_UP');self.assertEqual(len(result['items']),1)
        self.assertEqual((target/'financial-artifacts'/result['items'][0]['file']).read_bytes(),data)
        Path(art['path']).chmod(0o600);Path(art['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):backup(self.root,self.root/'another-backup')

    def test_notice_failure_does_not_spawn_another_notice_and_model_result_has_safe_companion(self):
        ident=self.add();good=self.bot();self.assertEqual(self.send(good),'TELEGRAM_ACCEPTED')
        self.assertEqual(good.sends[0][0],42)
        self.assertEqual(self.send(good),'TELEGRAM_ACCEPTED');self.assertEqual(good.sends[1][0],-100)
        self.assertNotIn('fixture',good.sends[1][1]['text'])
        from reporting.notification_reconciliation import notice
        notice(self.store,ident,'test','private notice');bad=self.bot(fail=TimeoutError())
        self.assertEqual(self.send(bad),'UNKNOWN')
        asyncio.run(recover(self.store,self.co,self.cfg,bad,self.root))
        with closing(self.store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_review_notices').fetchone()[0],1)
