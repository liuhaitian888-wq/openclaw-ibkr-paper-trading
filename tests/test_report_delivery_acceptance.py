"""Offline fault injection: no credentials loaded and no real network allowed."""
import json
import multiprocessing as mp
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from scripts.report_delivery_guard import deliver
from scripts.send_daily_visual_feishu_update import _send_daily_visual_update
from scripts.send_feishu_report import FeishuBusinessRejected, validate_feishu_response
from scripts.daily_feishu_scheduler import evaluate


def worker(root, mode, started, release, queue):
    root = Path(root)
    def send():
        with (root/'remote_acceptances').open('a') as f:
            f.write('accepted\n'); f.flush(); os.fsync(f.fileno())
        started.set()
        if mode == 'crash': os._exit(23)
        if mode == 'hold': release.wait(10)
        return {'status':'sent','upload_confirmed':True,'image_key_valid':True,'message_business_success':True,'message_id':'om_mock'}
    result = deliver(root/'report.json',send,state_dir=root,
                     now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai')))
    queue.put(result['status'])


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.report=self.root/'report.json'
        self.report.write_text('{"trading_date":"2026-09-04"}')
        self.now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))

    def state(self):
        return next(iter(json.loads((self.root/'delivery.json').read_text())['reports'].values()))

    def inject(self, upload_error=None, send_error=None, response='{"code":0}', ready=True):
        manifest={'image_path':'/tmp/mock.png','html_path':'/tmp/mock.html',
                  'image_size':1,'image_width':1200,'image_height':1600}
        with ExitStack() as stack:
            stack.enter_context(patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')))
            prefix='scripts.send_daily_visual_feishu_update.'
            for name in ['load_env_file','require_target','write_local_qa_markdown']:
                stack.enter_context(patch(prefix+name))
            stack.enter_context(patch(prefix+'write_visual_report',return_value=manifest))
            stack.enter_context(patch(prefix+'feishu_image_capability',return_value={'ready':ready,'blocked_reason':'missing credentials'}))
            upload=stack.enter_context(patch(prefix+'upload_image',side_effect=upload_error,return_value='img_mock'))
            def transport(payload):
                if send_error: raise send_error
                validate_feishu_response(response,context='mock')
                return response
            send=stack.enter_context(patch(prefix+'send_webhook_payload',side_effect=transport))
            result=deliver(self.report,lambda:_send_daily_visual_update(output_dir=self.root),state_dir=self.root,now=self.now)
            duplicate=deliver(self.report,lambda: self.fail('retry forbidden'),state_dir=self.root,now=self.now)
            self.assertIn(duplicate['status'],['DUPLICATE','BLOCKED'])
            return result,upload.call_count,send.call_count

    def test_A_image_upload_failure(self):
        result,uploads,sends=self.inject(upload_error=FeishuBusinessRejected('upload rejected'))
        self.assertEqual((result['status'],uploads,sends),('FAILED',1,0))
        self.assertTrue(self.state()['requires_review'])

    def test_B_message_rejected(self):
        self.assertEqual(self.inject(send_error=FeishuBusinessRejected('rejected'))[0]['status'],'FAILED')

    def test_C_http_timeout(self):
        self.assertEqual(self.inject(upload_error=TimeoutError())[0]['status'],'UNKNOWN')

    def test_D_http_200_business_failure(self):
        self.assertEqual(self.inject(response='{"code":19001}')[0]['status'],'FAILED')

    def test_E_uploaded_message_timeout(self):
        result,uploads,sends=self.inject(send_error=TimeoutError())
        self.assertEqual((result['status'],uploads,sends),('UNKNOWN',1,1))
        self.assertEqual(self.state()['status'],'UNKNOWN')

    def test_F_crash_after_remote_acceptance(self):
        ctx=mp.get_context('spawn');started=ctx.Event();release=ctx.Event();q=ctx.Queue()
        p=ctx.Process(target=worker,args=(str(self.root),'crash',started,release,q));p.start();p.join(10)
        self.assertEqual(p.exitcode,23)
        self.assertEqual(self.state()['status'],'SENDING')
        result=deliver(self.report,lambda:self.fail('must not resend'),state_dir=self.root,now=self.now)
        self.assertEqual(result['status'],'DUPLICATE')
        self.assertEqual(self.state()['status'],'UNKNOWN')
        self.assertTrue(self.state()['requires_review'])
        self.assertEqual((self.root/'remote_acceptances').read_text().count('accepted'),1)

    def test_G_two_independent_processes(self):
        ctx=mp.get_context('spawn');started=ctx.Event();release=ctx.Event();q=ctx.Queue()
        p1=ctx.Process(target=worker,args=(str(self.root),'hold',started,release,q));p1.start()
        try:
            self.assertTrue(started.wait(10))
            p2=ctx.Process(target=worker,args=(str(self.root),'normal',started,release,q));p2.start();p2.join(10)
            self.assertEqual(p2.exitcode,0);self.assertEqual(q.get(timeout=2),'LOCKED')
        finally:
            release.set();p1.join(10)
        self.assertEqual(p1.exitcode,0);self.assertEqual(q.get(timeout=2),'SENT_CONFIRMED')
        self.assertEqual((self.root/'remote_acceptances').read_text().count('accepted'),1)

    def test_H_hash_and_render_version_changed(self):
        deliver(self.report,lambda:{'status':'sent','upload_confirmed':True,'image_key_valid':True,'message_business_success':True,'message_id':'om_mock'},state_dir=self.root,now=self.now)
        self.report.write_text('{"trading_date":"2026-09-04","report_version":999,"generated_at":"new"}')
        self.assertEqual(deliver(self.report,lambda:self.fail('resend'),state_dir=self.root,now=self.now)['status'],'DUPLICATE')

    def test_I_fresh_process_restart(self):
        ctx=mp.get_context('spawn');started=ctx.Event();release=ctx.Event();q=ctx.Queue()
        for expected in ['SENT_CONFIRMED','DUPLICATE']:
            p=ctx.Process(target=worker,args=(str(self.root),'normal',started,release,q));p.start();p.join(10)
            self.assertEqual(p.exitcode,0);self.assertEqual(q.get(timeout=2),expected)
        self.assertEqual((self.root/'remote_acceptances').read_text().count('accepted'),1)

    def test_J_next_day_new_report(self):
        deliver(self.report,lambda:{'status':'sent','upload_confirmed':True,'image_key_valid':True,'message_business_success':True,'message_id':'om_mock'},state_dir=self.root,now=self.now)
        self.report.write_text('{"trading_date":"2026-09-07"}')
        now=datetime(2026,9,7,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(deliver(self.report,lambda:{'status':'sent','upload_confirmed':True,'image_key_valid':True,'message_business_success':True,'message_id':'om_mock'},state_dir=self.root,now=now)['status'],'SENT_CONFIRMED')

    def test_parsing_failure_and_connection_reset_are_unknown(self):
        self.assertEqual(self.inject(response='not-json')[0]['status'],'UNKNOWN')
        for response in ['{}','[]','{"code":false}','{"code":0,"StatusCode":1}']:
            with self.assertRaises(RuntimeError):validate_feishu_response(response,context='mock')

    def test_connection_reset(self):
        self.assertEqual(self.inject(send_error=ConnectionResetError())[0]['status'],'UNKNOWN')

    def test_Berlin_summer_and_winter(self):
        for month,berlin_hour in [(7,3),(1,2)]:
            berlin=datetime(2026,month,15,berlin_hour,0,tzinfo=ZoneInfo('Europe/Berlin'))
            self.assertTrue(evaluate(berlin,None).due)
            self.assertEqual(berlin.astimezone(timezone.utc).hour,1)
            self.assertEqual(berlin.astimezone(ZoneInfo('Asia/Shanghai')).hour,9)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):deliver(self.report,lambda:None,state_dir=self.root,now=datetime(2026,9,6,9))

    def test_missing_credentials_local_blocked(self):
        result,uploads,sends=self.inject(ready=False)
        self.assertEqual((result['status'],uploads,sends),('BLOCKED',0,0))

class RetryTests(unittest.TestCase):
    def test_three_low_frequency_failures_and_one_local_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'r.json';p.write_text('{"trading_date":"2026-09-04"}')
            calls=[]
            def fail():calls.append(1);return {'status':'FAILED','error':'explicit rejection'}
            def run(h,m):return deliver(p,fail,state_dir=root,now=datetime(2026,9,6,h,m,tzinfo=ZoneInfo('Asia/Shanghai')))
            for h,m in [(9,0),(9,1),(9,5),(9,29),(9,30),(9,31),(10,0),(10,0),(10,1)]:run(h,m)
            self.assertEqual(len(calls),3)
            state=json.loads((root/'delivery.json').read_text());r=next(iter(state['reports'].values()))
            self.assertEqual(r['attempts'],3);self.assertTrue(r['warning']['local_only']);self.assertEqual(len(r['history']),3)
            warning=r['warning'];run(11,0)
            self.assertEqual(next(iter(json.loads((root/'delivery.json').read_text())['reports'].values()))['warning'],warning)

    def test_success_without_id_is_unknown_and_never_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'r.json';p.write_text('{"trading_date":"2026-09-04"}')
            now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))
            self.assertEqual(deliver(p,lambda:{'status':'sent'},state_dir=root,now=now)['status'],'UNKNOWN')
            self.assertEqual(deliver(p,lambda:self.fail('resend'),state_dir=root,now=now.replace(minute=30))['status'],'DUPLICATE')

    def test_guard_loads_both_explicit_env_files(self):
        from scripts.send_daily_visual_feishu_update import DEFAULT_ENV_FILE,DEFAULT_UPLOAD_ENV_FILE
        with patch('scripts.send_daily_visual_feishu_update.load_env_file') as load,patch('scripts.send_daily_visual_feishu_update.require_target',side_effect=RuntimeError('stop before rendering')):
            with self.assertRaises(RuntimeError):_send_daily_visual_update()
            self.assertEqual([c.args[0] for c in load.call_args_list],[DEFAULT_ENV_FILE,DEFAULT_UPLOAD_ENV_FILE])

class TransportIsolationTests(unittest.TestCase):
    def test_direct_transport_cannot_bypass_guard(self):
        from scripts.send_feishu_report import send_webhook_payload
        with patch('pathlib.Path.exists',return_value=False),patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(RuntimeError,'guarded sender'):
                send_webhook_payload({'msg_type':'image'})
            network.assert_not_called()

    def test_webhook_success_without_id_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            prefix='scripts.send_daily_visual_feishu_update.'
            for name in ['load_env_file','require_target','write_local_qa_markdown']:
                stack.enter_context(patch(prefix+name))
            stack.enter_context(patch(prefix+'write_visual_report',return_value={'image_path':'mock.png','html_path':'mock.html','image_size':1,'image_width':64,'image_height':64}))
            stack.enter_context(patch(prefix+'feishu_image_capability',return_value={'ready':True}))
            stack.enter_context(patch(prefix+'upload_image',return_value='img_mock'))
            stack.enter_context(patch(prefix+'send_webhook_payload',return_value='{"code":0,"data":{}}'))
            result=_send_daily_visual_update(output_dir=Path(tmp))
            self.assertEqual(result['status'],'SENT_ACCEPTED')
            self.assertIsNone(result['message_id'])
