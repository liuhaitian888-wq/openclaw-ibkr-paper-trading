import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo
from scripts.report_production_scheduler import run,readiness

class SchedulerTests(unittest.TestCase):
    def test_pause_window_and_readiness_never_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'r.json';send=Mock()
            now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai'))
            (root/'PAUSED').touch()
            self.assertEqual(run(now,p,root,send)['status'],'PAUSED');(root/'PAUSED').unlink()
            self.assertEqual(run(now.replace(hour=12),p,root,send)['status'],'OUTSIDE_WINDOW')
            self.assertEqual(run(now,p,root,send)['status'],'NOT_READY')
            run(now.replace(minute=30),p,root,send)
            self.assertEqual(len(list(root.glob('readiness-*.json'))),1);send.assert_not_called()

    def test_fresh_file_routes_once_to_guarded_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'r.json';p.write_text('{"trading_date":"2026-09-04"}')
            now=datetime(2026,9,6,9,0,tzinfo=ZoneInfo('Asia/Shanghai'));os.utime(p,(now.timestamp(),now.timestamp()))
            send=Mock(return_value={'status':'SENT_ACCEPTED'})
            self.assertEqual(run(now,p,root,send)['status'],'SENT_ACCEPTED');send.assert_called_once_with(report_path=p)

    def test_yesterday_report_is_not_backfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json';p.write_text('{"trading_date":"2026-09-04"}')
            old=datetime(2026,9,5,9,0,tzinfo=ZoneInfo('Asia/Shanghai'));os.utime(p,(old.timestamp(),old.timestamp()))
            self.assertFalse(readiness(p,old.replace(day=6))['ready'])

    def test_berlin_dst_independent_window(self):
        for month,hour in [(7,3),(1,2)]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);send=Mock();now=datetime(2026,month,15,hour,0,tzinfo=ZoneInfo('Europe/Berlin'))
                self.assertEqual(run(now,root/'absent',root,send)['status'],'NOT_READY');send.assert_not_called()

    def test_expired_failed_attempt_warns_once_without_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);send=Mock();p=root/'delivery.json'
            p.write_text(json.dumps({'reports':{'r':{'report_id':'r','status':'FAILED','attempt_date':'2026-09-06'}}}))
            now=datetime(2026,9,6,11,0,tzinfo=ZoneInfo('Asia/Shanghai'))
            run(now,root/'absent',root,send);first=p.read_text()
            run(now.replace(minute=30),root/'absent',root,send)
            self.assertEqual(p.read_text(),first);send.assert_not_called()
            self.assertEqual(json.loads(first)['reports']['r']['warning_status'],'LOCAL_WARNING')
