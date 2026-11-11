"""Development replies retain authenticated native provenance under publication-v2."""
import asyncio
from contextlib import closing
import copy
import json
import unittest
from reporting.engineering_development import notice,tool
from reporting.secretary_queue import accept_update
from reporting.notification_center import get_item
from reporting.publication_policy import decision
from reporting.incident_telegram import send_one
from reporting.recovery import RecoveryCoordinator
import test_engineering_development as development
import test_notification_center as fixtures

CFG={**fixtures.CFG,'automatic_updates_to_group':True,'automatic_notification_policy':'publication-v2','account_report_policy':'shared_group'}

class DevelopmentPublicationTests(unittest.TestCase):
    def setUp(self):
        development.DevelopmentTests.setUp(self)
        self.store=development.IncidentStore(self.root/'runtime/recovery.sqlite3',clock=lambda:self.now)
        self.co=RecoveryCoordinator(self.store.path)
        update={'update_id':71,'message':{'message_id':19,'date':1000,'text':'Investigate the approved policy defect',
            'from':{'id':42,'is_bot':False},'chat':{'id':42,'type':'private'}}}
        self.assertTrue(accept_update(self.a,update,CFG,armed_at=900))
        self.ins='telegram:42:71';self.a.reserve_run('native-run',instruction=self.ins,model='gpt-6.1-sol')
        self.task=tool(self.a,self.root,{'name':'engineering_development_submit','proposal_id':self.proposal},self.value,
            instruction=self.ins,run='native-run')['task_id']

    def item(self,stage='RESULT',config=None,identity=None):
        notice(self.a,self.store,identity or self.task,stage,'Bounded engineering result',config=CFG if config is None else config)
        with closing(self.store.connect()) as c:ident=c.execute('SELECT max(id) FROM notification_outbox').fetchone()[0]
        return get_item(self.store,ident)

    def test_real_ingress_three_stages_use_existing_private_sender_once_no_group(self):
        for stage in ('ACCEPTED','RESULT','UNKNOWN'):
            item=self.item(stage);self.assertEqual('owner',decision(item,CFG)['audience'])
            self.assertEqual(self.ins,item['payload']['instruction'])
            self.assertTrue(item['payload']['native_owner_reply'])
        bot=fixtures.NotificationCenterTests.bot(self)
        for _ in range(3):self.assertEqual('TELEGRAM_ACCEPTED',asyncio.run(send_one(self.store,self.co,CFG,report_root=self.root,owned_bot=bot,clock=lambda:self.now)))
        self.assertEqual([42,42,42],[x[0] for x in bot.sends])
        before=[]
        with closing(self.store.connect()) as c:before=c.execute('SELECT id,status,payload FROM notification_outbox').fetchall()
        for stage in ('ACCEPTED','RESULT','UNKNOWN'):self.item(stage)
        with closing(self.store.connect()) as c:self.assertEqual(before,c.execute('SELECT id,status,payload FROM notification_outbox').fetchall())
        self.assertEqual('EMPTY',asyncio.run(send_one(self.store,self.co,CFG,report_root=self.root,owned_bot=bot,clock=lambda:self.now)))

    def test_forged_non_native_stale_rotated_and_missing_receipt_do_not_gain_private_route(self):
        with closing(self.a.connect()) as c:
            original=c.execute('SELECT origin,kind,payload FROM secretary_events WHERE occurrence=?',(self.ins,)).fetchone()
        cases=['model','standing','autonomous','missing_received','forwarded','edited','bot','group','old','rotated','unverified','foreign_task','foreign_run','future_receive','config_missing']
        for case in cases:
            with self.subTest(case=case):
                cfg=copy.deepcopy(CFG);data=json.loads(original[2]);origin,kind=original[:2];identity=self.task
                with closing(self.store.connect()) as c,c:c.execute('DELETE FROM notification_outbox')
                with closing(self.a.connect()) as c,c:
                    c.execute('INSERT OR REPLACE INTO secretary_received VALUES (?,1000)',(self.ins,))
                    c.execute('UPDATE secretary_runs SET instruction=? WHERE occurrence=?',(self.ins,'native-run'))
                    if case=='model':origin='MODEL'
                    elif case=='standing':kind='STANDING_AUTHORIZATION'
                    elif case=='autonomous':kind='AUTONOMOUS_INSTRUCTION'
                    elif case=='missing_received':c.execute('DELETE FROM secretary_received WHERE instruction=?',(self.ins,))
                    elif case in ('forwarded','edited'):data['native_authority'][case]=True
                    elif case=='bot':data['native_authority']['is_bot']=True
                    elif case=='group':data['native_authority']['chat_type']='supergroup'
                    elif case=='old':data['timestamp']=899
                    elif case=='rotated':cfg.update(owner_user_id=43,owner_private_chat_id=43)
                    elif case=='unverified':cfg['owner_private_verified']=False
                    elif case=='config_missing':cfg={}
                    elif case=='foreign_task':identity='engineering-development:'+'f'*64
                    elif case=='foreign_run':c.execute('UPDATE secretary_runs SET instruction=? WHERE occurrence=?',('request','native-run'))
                    elif case=='future_receive':c.execute('UPDATE secretary_received SET received_at=1001 WHERE instruction=?',(self.ins,))
                    c.execute('UPDATE secretary_events SET origin=?,kind=?,payload=? WHERE occurrence=?',(origin,kind,json.dumps(data),self.ins))
                item=self.item(config=cfg,identity=identity)
                self.assertFalse(item['payload']['native_owner_reply']);self.assertEqual('archive',decision(item,CFG)['audience'])

    def test_existing_uncertain_or_suppressed_notice_is_never_rewritten(self):
        for status in ('UNKNOWN','STARTED','SUPPRESSED'):
            with closing(self.store.connect()) as c,c:c.execute('DELETE FROM notification_outbox')
            item=self.item()
            with closing(self.store.connect()) as c,c:c.execute('UPDATE notification_outbox SET status=? WHERE id=?',(status,item['id']))
            with closing(self.store.connect()) as c:before=c.execute('SELECT id,status,payload FROM notification_outbox').fetchall()
            notice(self.a,self.store,self.task,'RESULT','different content',config=CFG)
            with closing(self.store.connect()) as c:self.assertEqual(before,c.execute('SELECT id,status,payload FROM notification_outbox').fetchall())
