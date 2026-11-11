from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from reporting.incidents import IncidentStore
from reporting.recovery import RecoveryCoordinator
from reporting.report_schedule import BJ, due_types, enqueue_reports
from scripts.report_aggregation import period_for
from reporting.incident_feishu import send_one
from reporting.authentication_schedule import enqueue_authentication_notice


class ScheduleTests(unittest.TestCase):
    def test_weekly_auth_estimate_stages_and_restart_deduplication(self):
        now=datetime(2026,11,7,14,tzinfo=BJ)
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'db')
            self.assertTrue(enqueue_authentication_notice(store,now))
            self.assertFalse(enqueue_authentication_notice(store,now))
            item=self.accept(store)
            self.assertEqual(item['kind'],'AUTH_EXPECTED_24H')
            self.assertTrue(enqueue_authentication_notice(store,now+timedelta(hours=23)))
            self.assertFalse(enqueue_authentication_notice(store,now+timedelta(hours=23)))
    def make_report(self, root, kind, now, account='DU123'):
        directory=Path(root)/now.date().isoformat();directory.mkdir(exist_ok=True)
        (directory/(kind+'.json')).write_text(json.dumps(dict(
            generated_at=now.isoformat(),report_date=now.date().isoformat(),report_type=kind,
            account_id=account,environment='PAPER',source_validated=True,image_key='img_offline',
            source_snapshot_at=now.isoformat(),
            trading_period=period_for(kind,now),
            account={},performance={})))

    def accept(self, store):
        item=store.claim();store.finish(item['id'],'FEISHU_ACCEPTED');return item

    def test_overlap_one_bundle_and_one_same_day_supplement(self):
        now=datetime(2026,6,1,9,tzinfo=BJ)  # Monday and month start.
        self.assertEqual(due_types(now.date()), ['DAILY','WEEKLY','MONTHLY'])
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'db',clock=lambda:now.timestamp())
            self.make_report(tmp,'DAILY',now)
            self.assertEqual(enqueue_reports(store,tmp,'DU123',now-timedelta(seconds=1)), 'BEFORE_SCHEDULE')
            self.assertEqual(enqueue_reports(store,tmp,'DU123',now), 'REPORT_BUNDLE')
            item=self.accept(store)
            self.assertEqual(item['payload']['missing_reports'],['WEEKLY','MONTHLY'])
            self.assertEqual(item['payload']['scheduled_at'],now.timestamp())
            self.make_report(tmp,'WEEKLY',now)
            self.make_report(tmp,'MONTHLY',now)
            self.assertEqual(enqueue_reports(store,tmp,'DU123',now+timedelta(minutes=5)), 'REPORT_SUPPLEMENT')
            self.accept(store)
            self.assertEqual(enqueue_reports(store,tmp,'DU123',now+timedelta(hours=1)), 'NO_SUPPLEMENT')
            tomorrow=now+timedelta(days=1)
            self.assertEqual(enqueue_reports(store,tmp,'DU123',tomorrow), 'REPORT_BUNDLE')
            item=self.accept(store)
            self.assertEqual(item['payload']['included_reports'], [])

    def test_unknown_initial_blocks_supplement_and_wrong_account_is_missing(self):
        now=datetime(2026,6,1,9,tzinfo=BJ)
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'db',clock=lambda:now.timestamp())
            self.make_report(tmp,'DAILY',now,account='DU999')
            enqueue_reports(store,tmp,'DU123',now)
            item=store.claim();store.finish(item['id'],'UNKNOWN')
            self.assertEqual(item['payload']['included_reports'], [])
            self.make_report(tmp,'DAILY',now)
            self.assertEqual(enqueue_reports(store,tmp,'DU123',now), 'BLOCKED_INITIAL_UNCONFIRMED')

    def test_preflight_failures_are_bounded_and_survive_restart(self):
        now=[100000.0]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db';store=IncidentStore(path,clock=lambda:now[0]);coordinator=RecoveryCoordinator(path)
            store.ingest('fault','gateway',{'severity':'RED'})
            cfg={'transport':'feishu','target_name':'deehub',
                 'webhook_url':'https://open.feishu.cn/open-apis/bot/v2/hook/offline-fixture'}
            opener=Mock()
            self.assertEqual(send_one(store,coordinator,cfg,opener=opener,preflight=lambda _:False),'PENDING')
            self.assertEqual(send_one(store,coordinator,cfg,opener=opener,preflight=lambda _:False),'EMPTY')
            now[0]+=15;store=IncidentStore(path,clock=lambda:now[0])
            self.assertEqual(send_one(store,coordinator,cfg,opener=opener,preflight=lambda _:False),'PENDING')
            now[0]+=30
            self.assertEqual(send_one(store,coordinator,cfg,opener=opener,preflight=lambda _:False),'NOT_SENT_EXHAUSTED')
            now[0]+=86400
            self.assertEqual(send_one(store,coordinator,cfg,opener=opener,preflight=lambda _:True),'EMPTY')
            opener.assert_not_called()

    def test_pending_reminder_is_superseded_on_recovery(self):
        now=[100000.0]
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'db',clock=lambda:now[0]);store.ingest('fault','gateway',{})
            self.accept(store);now[0]+=1800;store.enqueue_due_reminders()
            store.ingest('recovered','gateway',{},resolved=True)
            self.assertEqual(store.claim()['kind'],'RECOVERY')
