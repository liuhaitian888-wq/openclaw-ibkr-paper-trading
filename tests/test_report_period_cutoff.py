from contextlib import closing
from datetime import datetime, timezone, timedelta, date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from reporting.financial_reports import prepare_reports
from reporting.report_schedule import ready_reports, enqueue_reports, BJ
from reporting.incidents import IncidentStore
from scripts.report_aggregation import period_for


def calendar(day):return day.weekday()<5 and day!=date(2026,4,3)


class ReportCutoffTests(unittest.TestCase):
    def observer(self, root, at):
        (root/'runtime').mkdir(exist_ok=True)
        (root/'runtime/paper-observer.latest.json').write_text(json.dumps(dict(source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',observed_at=at.isoformat(),positions=[],account={})))

    def manifest(self, root, now, *, period=None, source=None):
        directory=root/now.astimezone(BJ).date().isoformat();directory.mkdir(exist_ok=True)
        value=dict(report_date=str(now.astimezone(BJ).date()),report_type='DAILY',generated_at=now.isoformat(),source_snapshot_at=(source or now).isoformat(),source_validated=True,account_id='DU123',environment='PAPER',image_key='img_fixture',account={},performance={},trading_period=period or period_for('DAILY',now))
        (directory/'DAILY.json').write_text(json.dumps(value));return value

    @patch('scripts.report_aggregation.trading_day',side_effect=calendar)
    def test_winter_preview_does_not_cross_cutoff_or_relabel_source_and_supplements_once(self,_):
        before=datetime(2026,11,10,0,59,31,tzinfo=timezone.utc);source=before-timedelta(seconds=11);after=before+timedelta(seconds=29)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.observer(root,source);calls=[]
            def publish(*args):calls.append(1);return 'img_fixture'
            built=prepare_reports(root,'DU123',before,publish_image=publish);path=Path(built['directory'])/'DAILY.json';old=json.loads(path.read_text())
            self.assertEqual(old['trading_period']['start_date'],'2026-11-06')
            result=prepare_reports(root,'DU123',after,publish_image=publish)
            self.assertEqual(result['status'],'SOURCE_UNVERIFIED')
            self.assertIn('SOURCE_BEFORE_SESSION_CLOSE',result['source_check']['reason_codes'])
            self.assertEqual(len(calls),1)
            store=IncidentStore(root/'queue',clock=lambda:after.timestamp())
            enqueue_reports(store,root/'reports/financial','DU123',after)
            item=store.claim();self.assertEqual(item['payload']['included_reports'],[]);self.assertIn('交易期间',item['payload']['reason']);store.finish(item['id'],'FEISHU_ACCEPTED')
            completed=after+timedelta(seconds=5);self.observer(root,completed)
            prepare_reports(root,'DU123',completed,publish_image=publish);new=json.loads(path.read_text())
            self.assertEqual(new['trading_period']['start_date'],'2026-11-09');self.assertEqual(new['source_snapshot_at'],completed.isoformat())
            self.assertEqual(enqueue_reports(store,root/'reports/financial','DU123',completed),'REPORT_SUPPLEMENT')
            supplement=store.claim();self.assertIn('报告日',supplement['payload']['reason']);self.assertIn('交易期间',supplement['payload']['reason']);store.finish(supplement['id'],'FEISHU_ACCEPTED')
            self.assertEqual(enqueue_reports(store,root/'reports/financial','DU123',completed),'NO_SUPPLEMENT')

    @patch('scripts.report_aggregation.trading_day',side_effect=calendar)
    def test_same_source_timestamp_does_not_reuse_wrong_period_cache(self,_):
        now=datetime(2026,11,10,1,0,5,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.observer(root,now);calls=[]
            def publish(*args):calls.append(1);return 'img_fixture'
            result=prepare_reports(root,'DU123',now,publish_image=publish);path=Path(result['directory'])/'DAILY.json';r=json.loads(path.read_text())
            r['trading_period']=period_for('DAILY',now-timedelta(minutes=1));path.write_text(json.dumps(r))
            prepare_reports(root,'DU123',now,publish_image=publish)
            self.assertEqual(len(calls),2);self.assertEqual(json.loads(path.read_text())['trading_period']['start_date'],'2026-11-09')
            html=path.with_suffix('.html').read_text();self.assertIn('Report date (Beijing)',html);self.assertIn('Trading period:',html)

    @patch('scripts.report_aggregation.trading_day',side_effect=calendar)
    def test_dispatch_rejects_old_period_and_preclose_source_separately(self,_):
        now=datetime(2026,11,10,1,0,5,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.manifest(root,now,period=period_for('DAILY',now-timedelta(minutes=1)))
            ready,missing=ready_reports(root,now.astimezone(BJ).date(),'DU123',now)
            self.assertFalse(ready);self.assertIn('交易期间',missing['DAILY'])
            self.manifest(root,now,source=now-timedelta(seconds=6))
            ready,missing=ready_reports(root,now.astimezone(BJ).date(),'DU123',now)
            self.assertFalse(ready);self.assertIn('源快照',missing['DAILY'])
            self.manifest(root,now)
            ready,missing=ready_reports(root,now.astimezone(BJ).date(),'DU123',now);self.assertIn('DAILY',ready);self.assertFalse(missing)

    @patch('scripts.report_aggregation.trading_day',side_effect=calendar)
    def test_summer_dst_weekend_and_holiday_keep_existing_complete_session_policy(self,_):
        cases=[('2026-07-07T09:00:00+08:00','2026-07-06',21),('2026-11-10T09:00:00+08:00','2026-11-09',20),('2026-03-09T09:00:00+08:00','2026-03-06',21),('2026-11-02T09:00:00+08:00','2026-10-30',20),('2026-11-08T09:00:00+08:00','2026-11-06',20),('2026-04-04T09:00:00+08:00','2026-04-02',21)]
        for value,expected,hour in cases:
            now=datetime.fromisoformat(value);p=period_for('DAILY',now)
            with self.subTest(value=value):
                self.assertEqual(now.astimezone(ZoneInfo('America/New_York')).hour,hour);self.assertEqual(p['start_date'],expected)
                close=datetime.fromisoformat(p['last_session_close_utc']);self.assertEqual(close.astimezone(ZoneInfo('America/New_York')).hour,20);self.assertLessEqual(close,now)
        summer=datetime(2026,7,7,0,59,31,tzinfo=timezone.utc)
        self.assertEqual(period_for('DAILY',summer)['start_date'],period_for('DAILY',summer+timedelta(seconds=29))['start_date'])
