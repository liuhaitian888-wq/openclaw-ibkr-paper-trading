from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from reporting.incidents import IncidentStore
from reporting.notification_access import decision,record_member,member,allowed
from reporting.notification_center import recipient,render
from test_notification_center import CFG


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.cfg={**CFG,'automatic_updates_to_group':True,'account_report_policy':'shared_group'}

    def item(self,**p):return dict(id=1,incident_key='secretary:research',kind='SECRETARY_REPLY',payload={'message_role':'RESEARCH',**p})

    def test_sensitive_metadata_and_text_override_public_labels(self):
        for payload in ({'account_id':'DU12345'}, {'data_classification':'security'}, {'reason':'账户余额 EUR 100'},
                        {'nested':{'positions':[{'symbol':'AAPL'}]}}, {'web_app_url':'https://example.invalid'}):
            with self.subTest(payload=payload):
                item=self.item(fixed_public_status=True,**payload)
                self.assertEqual(decision(item,self.cfg)['audience'],'owner')
                self.assertEqual(recipient(item,self.cfg),42)

    def test_unknown_free_text_stays_private_and_fixed_public_status_copies_nothing(self):
        item=self.item(reason='unclassified model prose')
        self.assertEqual(recipient(item,self.cfg),42)
        item['payload']['fixed_public_status']=True
        view=render(item,self.cfg,1)
        self.assertEqual(view['chat_id'],-100)
        self.assertNotIn('unclassified',view['text'])

    def test_auth_immediate_action_and_private_notice_are_private(self):
        for p in ({'message_role':'AUTH'},{'requires_response':True},{'private_notice':True},{'phase':'OPERATOR'}):
            self.assertEqual(decision(self.item(**p),self.cfg)['audience'],'owner')

    def test_report_policy_is_explicit_and_does_not_authorize_other_account_posts(self):
        item=dict(id=1,kind='REPORT_BUNDLE',incident_key='daily',payload={'included_reports':['DAILY'],'data_classification':'private_account'})
        self.assertEqual(recipient(item,self.cfg),-100)
        self.assertEqual(recipient(item,{**self.cfg,'account_report_policy':'private'}),42)
        for policy in (None,'hold','typo'):
            with self.assertRaises(PermissionError):recipient(item,{**self.cfg,'account_report_policy':policy})
        self.assertEqual(recipient(self.item(account_id='DU12345'),self.cfg),42)

    def test_member_tags_do_not_grant_capabilities_and_revoke_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'recovery.sqlite3')
            self.assertFalse(allowed(store,-100,88,'public_research'))
            def record(**overrides):
                data=dict(chat_id=-100,user_id=88,tags=['研究协作者'],capabilities=[],approved_by=42,source='telegram:42:1')
                record_member(store,self.cfg,**{**data,**overrides})
            record();record()
            self.assertFalse(allowed(store,-100,88,'public_research'))
            record(capabilities=['public_research'],source='telegram:42:2')
            self.assertTrue(allowed(store,-100,88,'public_research'))
            self.assertFalse(allowed(store,-100,88,'control'))
            self.assertFalse(allowed(store,-200,88,'public_research'))
            record(capabilities=['public_research'],revoked=True,source='telegram:42:3')
            self.assertFalse(allowed(store,-100,88,'public_research'))
            self.assertTrue(member(store,-100,88)['revoked'])
            with closing(store.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM notification_membership').fetchone()[0],3)
            for changes in ({'approved_by':88},{'capabilities':['account']},{'capabilities':['control']},{'tags':['x'*17]}):
                with self.assertRaises(PermissionError):record(**changes)
