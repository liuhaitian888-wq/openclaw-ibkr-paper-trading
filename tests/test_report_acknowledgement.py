import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from scripts.report_acknowledgement import classify
from scripts.report_delivery_guard import deliver

class AcknowledgementTests(unittest.TestCase):
    def test_webhook_empty_data_is_accepted(self):
        result=classify('{"code":0,"StatusCode":0,"data":{},"msg":"success"}','custom_webhook')
        self.assertEqual(result['status'],'SENT_ACCEPTED');self.assertIsNone(result['message_id'])

    def test_app_requires_message_id(self):
        with self.assertRaises(RuntimeError):classify('{"code":0,"data":{}}','app_message_api')
        self.assertEqual(classify('{"code":0,"data":{"message_id":"om_test"}}','app_message_api')['status'],'SENT_CONFIRMED')

    def test_failure_and_bad_response_not_accepted(self):
        for response in ['{"code":1}', '{}','bad-json','{"code":false}','{"code":0,"StatusCode":2}']:
            with self.subTest(response=response),self.assertRaises(RuntimeError):classify(response,'custom_webhook')

    def test_both_success_states_persist_and_never_repeat(self):
        for transport,response in [('custom_webhook','{"code":0,"data":{}}'),('app_message_api','{"code":0,"data":{"message_id":"om_test"}}')]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);p=root/'report.json';p.write_text('{"trading_date":"2026-09-04"}')
                now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))
                result={**classify(response,transport),'upload_confirmed':True,'image_key_valid':True}
                self.assertEqual(deliver(p,lambda:result,state_dir=root,now=now)['status'],result['status'])
                for dt in [now.replace(minute=30),now.replace(day=7)]:
                    self.assertEqual(deliver(p,lambda:self.fail('duplicate'),state_dir=root,now=dt)['status'],'DUPLICATE')
                state=json.loads((root/'delivery.json').read_text());r=next(iter(state['reports'].values()))
                self.assertFalse(r['requires_review']);self.assertEqual(r['status'],result['status'])
                deliver(p,lambda:self.fail('off schedule'),state_dir=root,now=now.replace(hour=11))
                r=next(iter(json.loads((root/'delivery.json').read_text())['reports'].values()))
                self.assertNotIn('warning',r)

    def test_app_cannot_claim_accepted_without_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'r.json';p.write_text('{"trading_date":"2026-09-04"}')
            r={'status':'SENT_ACCEPTED','transport':'app_message_api','upload_confirmed':True,'image_key_valid':True,'message_business_success':True}
            result=deliver(p,lambda:r,state_dir=root,now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai')))
            self.assertEqual(result['status'],'UNKNOWN')
