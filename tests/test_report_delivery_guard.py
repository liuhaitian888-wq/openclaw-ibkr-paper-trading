import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from scripts.report_delivery_guard import deliver
from scripts.daily_feishu_scheduler import parse_now


class DeliveryTests(unittest.TestCase):
    def test_restart_refresh_and_next_day_cannot_resend_same_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); report = root/'report.json'
            report.write_text('{"trading_date":"2026-09-04"}')
            send = Mock(return_value={'status':'sent','upload_confirmed':True,'image_key_valid':True,'message_business_success':True,'message_id':'om_mock'})
            now = parse_now('2026-09-06T09:00:10+08:00')
            self.assertEqual(deliver(report,send,state_dir=root,now=now)['status'],'SENT_CONFIRMED')
            report.write_text('{"trading_date":"2026-09-04","generated_at":"new"}')
            for day in ['06','07']:
                deliver(report,send,state_dir=root,now=parse_now(f'2026-09-{day}T09:00:20+08:00'))
            self.assertEqual(send.call_count,1)
            self.assertEqual(json.loads((root/'delivery.json').read_text())['last_sent_report_id'],'daily:2026-09-04:scheduled-close')

    def test_pause_and_off_schedule_never_call_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); send=Mock(); report=root/'absent.json'
            (root/'PAUSED').touch()
            self.assertEqual(deliver(report,send,state_dir=root)['status'],'BLOCKED')
            (root/'PAUSED').unlink()
            self.assertEqual(deliver(report,send,state_dir=root,now=parse_now('2026-09-06T15:00:00+08:00'))['status'],'BLOCKED')
            send.assert_not_called()

    def test_failure_or_uncertain_response_never_retries(self):
        for exception in [False,True]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); report=root/'report.json';report.write_text('{"trading_date":"2026-09-04"}')
                send=Mock(side_effect=TimeoutError() if exception else None,return_value={'status':'image_failed'})
                now=parse_now('2026-09-06T09:00:10+08:00')
                try: deliver(report,send,state_dir=root,now=now)
                except TimeoutError: pass
                deliver(report,send,state_dir=root,now=now)
                self.assertEqual(send.call_count,1)
