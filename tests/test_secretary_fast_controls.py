from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from reporting.agent_secretary import SecretaryArchive
from reporting.incidents import IncidentStore
from reporting.secretary_queue import initialize, accept_update, claim, autonomous


class FastControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = SecretaryArchive(self.root/'agent_secretary.sqlite3', clock=lambda:100000)
        initialize(self.a)
        self.cfg = dict(chat_id=-100, owner_user_id=123, owner_private_chat_id=123, owner_private_verified=True,bot_token='test-only-placeholder')

    def update(self, uid=1, chat=123, text='你好'):
        return dict(update_id=uid, message=dict(chat=dict(id=chat, type='private' if chat>0 else 'supergroup'),
                    date=100000, message_id=uid, text=text, **{'from':dict(id=123,is_bot=False)}))

    def test_private_only_and_ack_repair_is_deduplicated(self):
        from reporting.secretary_queue import reconcile_acknowledgements
        self.assertFalse(accept_update(self.a,self.update(chat=-100,text='/gate'),self.cfg,armed_at=1))
        self.assertTrue(accept_update(self.a,self.update(),self.cfg,armed_at=1))
        self.assertTrue(accept_update(self.a,self.update(),self.cfg,armed_at=1))
        s=IncidentStore(self.root/'runtime/recovery.sqlite3')
        reconcile_acknowledgements(self.a,s); reconcile_acknowledgements(self.a,s)
        item=s.claim(); self.assertEqual(item['payload']['message_role'],'ACK')
        self.assertIsNone(s.claim())

    def test_confirmed_boundary_yields_to_user_and_never_replays_active_step(self):
        from reporting.secretary_queue import checkpoint
        autonomous(self.a,now=100000); research=claim(self.a,model='gpt-6.1-sol',now=100000)
        checkpoint(self.a,research['run'],dict(turn=1,step=1,transcript=[],usage=[]))
        accept_update(self.a,self.update(),self.cfg,armed_at=1)
        user=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.assertNotEqual(user['run'],research['run'])
        resumed=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.assertEqual(resumed['run'],research['run']); self.assertEqual(resumed['checkpoint']['turn'],1)
        self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=100000))
        self.a.finish_run(research['run'],state='UNKNOWN')
        self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=100000))

    def test_user_requested_research_also_yields_to_new_private_message(self):
        from reporting.secretary_queue import checkpoint
        accept_update(self.a,self.update(text='/research 深入检验'),self.cfg,armed_at=1)
        research=claim(self.a,model='gpt-6.1-sol',now=100000)
        checkpoint(self.a,research['run'],dict(turn=1,step=1,transcript=[],usage=[]))
        accept_update(self.a,self.update(uid=2,text='你好'),self.cfg,armed_at=1)
        user=claim(self.a,model='gpt-6.1-sol',now=100000)
        self.assertNotEqual(user['run'],research['run'])

    def test_menu_and_batch_rejection_and_confirmation(self):
        from reporting.secretary_controls import menu_commands, process_controls
        from reporting.telegram_gate import parse_batch, DEFAULT, current
        from reporting.gate_drafts import create_draft, confirm_draft
        self.assertEqual([x[0] for x in menu_commands()[:2]],['ready','gate'])
        good='QMAX=1\nOMAX=200\nRMAX=10\nSMAX=不限\nGMAX=不限'
        values=parse_batch(good)
        for bad in (good+'\nQMAX=2',good.replace('QMAX=1','QMAX=1.5'),good.replace('OMAX=200','OMAX=NaN'),good.replace('OMAX=200','OMAX=2 EUR'),good.replace('RMAX=10\n','')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):parse_batch(bad)
        d=create_draft(self.a,self.root,123,0,values,now=100)
        with self.assertRaises(PermissionError):confirm_draft(self.a,self.root,124,d['id'],now=101)
        with self.assertRaises(ValueError):confirm_draft(self.a,self.root,123,d['id'],now=701)
        result=confirm_draft(self.a,self.root,123,d['id'],now=101)
        self.assertEqual(result['revision'],1)
        self.assertEqual(confirm_draft(self.a,self.root,123,d['id'],now=999),result)
        self.assertEqual(current(self.root)['settings'],DEFAULT)
        stale=create_draft(self.a,self.root,123,1,values,now=100)
        other=create_draft(self.a,self.root,123,1,{**values,'max_quantity':2},now=100)
        confirm_draft(self.a,self.root,123,other['id'],now=101)
        with self.assertRaises(ValueError):confirm_draft(self.a,self.root,123,stale['id'],now=101)
        # Inbox must not interpret a Mini App's already-handled confirmation again.
        process_controls(self.a,self.root,dict(bot_username='fixture'))

    def test_signed_init_data_only_exact_owner_with_bounded_age(self):
        from reporting.gate_web import verify_init_data
        token='test-only-placeholder'
        data=dict(auth_date='100',user=json.dumps(dict(id=123,is_bot=False)))
        def signed(d):
            check='\n'.join(k+'='+v for k,v in sorted(d.items()))
            secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
            return urlencode({**d,'hash':hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()})
        self.assertEqual(verify_init_data(signed(data),token,123,now=101),123)
        for raw,now in ((signed(data)+'&auth_date=100',101),(signed(data),701),(signed(data),0),
                        (signed({**data,'user':json.dumps(dict(id=124))}),101),('hash=bad',101)):
            with self.assertRaises((ValueError,PermissionError)):verify_init_data(raw,token,123,now=now)

    def test_notification_priority_keeps_incident_order_and_unknown(self):
        s=IncidentStore(self.root/'recovery.sqlite3')
        with closing(s.connect()) as c,c:
            for key,kind,payload,status in [('research','SECRETARY_REPLY',{'message_role':'RESEARCH'},'PENDING'),
                  ('control','SECRETARY_REPLY',{'message_role':'CONTROL'},'PENDING'),
                  ('fault','ALERT',{'severity':'RED'},'UNKNOWN'),('fault','RECOVERY',{},'PENDING'),
                  ('urgent','ALERT',{'severity':'RED'},'PENDING')]:
                c.execute('INSERT INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,?,?,?)',(key,kind,json.dumps(payload),status))
        self.assertEqual(s.claim()['incident_key'],'urgent')
        self.assertEqual(s.claim()['incident_key'],'control')
        self.assertEqual(s.claim()['incident_key'],'research')
        self.assertIsNone(s.claim())

    def test_checkpoint_failure_and_restart_cannot_start_same_model_occurrence(self):
        from ops.cloud.secretary_rpc import dispatch
        accept_update(self.a,self.update(),self.cfg,armed_at=1)
        job=claim(self.a,model='gpt-6.1-sol',now=100000)
        request=dict(action='model_started',run=job['run'],turn=1)
        dispatch(self.root,request,self.cfg,{})
        with self.assertRaises(ValueError):dispatch(self.root,request,self.cfg,{})
        self.assertIsNone(claim(self.a,model='gpt-6.1-sol',now=100000))

    def test_draft_commit_crash_reconciles_file_without_second_version(self):
        from unittest.mock import patch
        from reporting.gate_drafts import create_draft,confirm_draft
        from reporting.telegram_gate import DEFAULT,current
        draft=create_draft(self.a,self.root,123,0,DEFAULT,now=100)
        with patch('reporting.telegram_gate.materialize',side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):confirm_draft(self.a,self.root,123,draft['id'],now=101)
        result=confirm_draft(self.a,self.root,123,draft['id'],now=999)
        self.assertEqual(result['revision'],1);self.assertEqual(current(self.root)['revision'],1)
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM secretary_gate_versions').fetchone()[0],1)

    def test_concurrent_previews_commit_exactly_one_version(self):
        from concurrent.futures import ThreadPoolExecutor
        from reporting.gate_drafts import create_draft,confirm_draft
        from reporting.telegram_gate import DEFAULT
        drafts=[create_draft(self.a,self.root,123,0,{**DEFAULT,'max_quantity':i},now=100) for i in (1,2)]
        def submit(d):
            try:return confirm_draft(self.a,self.root,123,d['id'],now=101)['revision']
            except ValueError:return 'STALE'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,drafts))
        self.assertCountEqual(results,[1,'STALE'])

    def test_old_history_is_not_given_a_new_received_ack_on_deployment(self):
        from reporting.secretary_queue import reconcile_acknowledgements
        self.a.append('telegram:123:0','der-secretary',origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'old'})
        store=IncidentStore(self.root/'runtime/recovery.sqlite3')
        reconcile_acknowledgements(self.a,store)
        self.assertIsNone(store.claim())

    def test_ack_backlog_larger_than_batch_drains_without_skipping_oldest(self):
        from reporting.secretary_queue import reconcile_acknowledgements
        for uid in range(1,108):accept_update(self.a,self.update(uid=uid),self.cfg,armed_at=1)
        store=IncidentStore(self.root/'runtime/recovery.sqlite3')
        reconcile_acknowledgements(self.a,store);reconcile_acknowledgements(self.a,store)
        with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0],107)

    def test_invalid_form_preview_never_writes_cap_version(self):
        from reporting.gate_web import dispatch
        from reporting.telegram_gate import DEFAULT,current
        from unittest.mock import patch
        with patch('reporting.gate_web.verify_init_data',return_value=123):
            with self.assertRaises(ValueError):dispatch(self.a,self.root,self.cfg,{'numeric_gate_controls_approved':True},'/api/preview',
                {'initData':'test','revision':0,'settings':{**DEFAULT,'max_quantity':'1.5'}})
        self.assertEqual(current(self.root)['revision'],0)
