from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.financial_reports import prepare_reports
from scripts.report_aggregation import period_for
from reporting.report_schedule import BJ


class BuilderTests(unittest.TestCase):
    def test_exact_fresh_readback_builds_existing_white_grid_without_fake_pnl(self):
        now=datetime(2026,11,5,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            data={'source':'REAL_IBKR','complete':True,'environment':'PAPER','account_id':'DU123',
                  'observed_at':now.isoformat(),'positions':[], 'account':{
                      'net_liquidation':{'value':100,'currency':'EUR','source_timestamp':now.isoformat()}}}
            (root/'runtime/paper-observer.latest.json').write_text(json.dumps(data))
            result=prepare_reports(root,'DU123',now,publish_image=lambda *_:'img_offline')
            self.assertEqual(result['status'],'PREPARED')
            directory=Path(result['directory']);report=json.loads((directory/'DAILY.json').read_text())
            self.assertEqual(report['account']['net_liquidation']['value'],100)
            self.assertIsNone(report['account']['daily_pnl']['value'])
            self.assertFalse(report['performance']['complete_daily_pnl'])
            self.assertIn('background:#fff',(directory/'DAILY.html').read_text())
            self.assertEqual(prepare_reports(root,'DU999',now)['status'],'SOURCE_UNVERIFIED')
            self.assertEqual(prepare_reports(root,'DU123',now+timedelta(seconds=601))['status'],'SOURCE_UNVERIFIED')

    def test_rejection_diagnostics_preserve_predicates_without_private_values(self):
        from reporting.financial_reports import source_diagnostics
        now=datetime(2026,11,5,1,tzinfo=timezone.utc)
        good=dict(source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',observed_at=now.isoformat())
        cases=[({'source':'SECRET_PRIVATE_SOURCE'},'SOURCE_NOT_REAL_IBKR'),
               ({'complete':False},'SOURCE_INCOMPLETE'),({'environment':'LIVE'},'ENVIRONMENT_MISMATCH'),
               ({'account_id':'PRIVATE_ACCOUNT'},'ACCOUNT_MISMATCH'),
               ({'observed_at':'invalid'},'SOURCE_TIME_INVALID'),
               ({'observed_at':(now-timedelta(seconds=601)).isoformat()},'SOURCE_STALE'),
               ({'observed_at':(now+timedelta(seconds=1)).isoformat()},'SOURCE_IN_FUTURE')]
        for change,code in cases:
            with self.subTest(code=code):
                check=source_diagnostics({**good,**change},'DU123',now)
                self.assertEqual(check['reason_codes'],[code])
                self.assertNotIn('PRIVATE',json.dumps(check))
        self.assertEqual(source_diagnostics(good,'DU123',now.replace(tzinfo=None))['reason_codes'],['CURRENT_TIME_INVALID'])
        self.assertEqual(source_diagnostics({**good,'observed_at':(now-timedelta(seconds=600)).isoformat()},'DU123',now)['reason_codes'],[])
        check=source_diagnostics(good,'DU123',now)
        self.assertEqual(check['snapshot_sha256'],source_diagnostics(dict(reversed(list(good.items()))),'DU123',now)['snapshot_sha256'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            (root/'runtime/paper-observer.latest.json').write_text(json.dumps({**good,'complete':False,'account_id':'PRIVATE_ACCOUNT'}))
            with patch('scripts.report_rendering.render_html') as renderer:
                result=prepare_reports(root,'DU123',now)
            self.assertEqual(result['status'],'SOURCE_UNVERIFIED')
            self.assertEqual(result['source_check']['reason_codes'],['SOURCE_INCOMPLETE','ACCOUNT_MISMATCH'])
            self.assertFalse((root/'reports').exists());renderer.assert_not_called()

    def test_source_sidecar_is_bound_frozen_and_survives_observer_replacement(self):
        import hashlib
        from reporting.incidents import IncidentStore
        from reporting.report_schedule import enqueue_reports, ready_reports
        now=datetime(2026,11,10,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            data=dict(source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',observed_at=now.isoformat(),positions=[],account={})
            observer=root/'runtime/paper-observer.latest.json';observer.write_text(json.dumps(data))
            def publisher(html,png):png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'offline');return None
            result=prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram')
            directory=Path(result['directory']);manifest=json.loads((directory/'DAILY.json').read_text())
            source=Path(manifest['source_snapshot']['path']);original=source.read_bytes()
            self.assertEqual(json.loads(original),data)
            self.assertEqual(manifest['source_snapshot']['sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(source.stat().st_mode&0o777,0o600)
            observer.write_text(json.dumps({**data,'account_id':'DU999'}))
            store=IncidentStore(root/'queue.sqlite3',clock=lambda:now.timestamp())
            self.assertEqual(enqueue_reports(store,root/'reports/financial','DU123',now,transport='telegram'),'REPORT_BUNDLE')
            with __import__('contextlib').closing(store.connect()) as c:
                payload=json.loads(c.execute('SELECT payload FROM notification_outbox').fetchone()[0])
            self.assertEqual(payload['source_provenance_missing'],[])
            frozen=Path(payload['source_snapshots'][0]['path']);self.assertEqual(frozen.read_bytes(),original)
            from reporting.notification_artifacts import backup
            copied=backup(root,root/'backup-copy')
            self.assertIn(frozen.name,[Path(x['file']).name for x in copied['items']])
            source.write_text('{}')
            self.assertEqual(frozen.read_bytes(),original)
            ready,missing=ready_reports(root/'reports/financial',now.astimezone(BJ).date(),'DU123',now,transport='telegram')
            self.assertEqual(ready,{});self.assertIn('DAILY',missing)

    def test_source_preview_cache_upgrades_and_refuses_malformed_evidence(self):
        from reporting.report_schedule import ready_reports
        now=datetime(2026,11,10,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            data=dict(source='REAL_IBKR',complete=True,environment='PAPER',account_id='DU123',observed_at=now.isoformat(),positions=[],account={})
            (root/'runtime/paper-observer.latest.json').write_text(json.dumps(data));calls=[]
            def publisher(html,png):calls.append(1);png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'offline');return None
            result=prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram')
            path=Path(result['directory'])/'DAILY.json';report=json.loads(path.read_text())
            source=Path(report['source_snapshot']['path'])
            report.pop('source_snapshot');report.pop('source_check');path.write_text(json.dumps(report))
            prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram');self.assertEqual(len(calls),2)
            prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram');self.assertEqual(len(calls),2)
            report=json.loads(path.read_text());incomplete=dict(report);incomplete.pop('source_snapshot');path.write_text(json.dumps(incomplete))
            ready,missing=ready_reports(root/'reports/financial',now.astimezone(BJ).date(),'DU123',now,transport='telegram')
            self.assertFalse(ready);self.assertIn('DAILY',missing)
            report['source_check']=None;path.write_text(json.dumps(report))
            ready,missing=ready_reports(root/'reports/financial',now.astimezone(BJ).date(),'DU123',now,transport='telegram')
            self.assertFalse(ready);self.assertIn('DAILY',missing)
            prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram');self.assertEqual(len(calls),3)
            source.unlink()  # Only this test's isolated preview.
            prepare_reports(root,'DU123',now,publish_image=publisher,transport='telegram');self.assertEqual(len(calls),4)
            self.assertTrue(source.is_file())

    def test_monday_weekly_period_is_previous_week_and_dst_aware(self):
        with patch('scripts.report_aggregation.trading_day',side_effect=lambda d:d.weekday()<5):
            period=period_for('WEEKLY',datetime(2026,11,2,9,tzinfo=BJ))
        self.assertEqual(period['start_date'],'2026-10-26')
        self.assertEqual(period['end_date_exclusive'],'2026-11-01')

    def test_font_renderer_revision_rebuilds_and_zero_positions_are_not_counted(self):
        now=datetime(2026,11,5,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            data={'source':'REAL_IBKR','complete':True,'environment':'PAPER','account_id':'DU123','observed_at':now.isoformat(),
                  'positions':[{'position':'0'},{'position':'8'}],'account':{}}
            (root/'runtime/paper-observer.latest.json').write_text(json.dumps(data));calls=[]
            def publisher(*args):calls.append(args);return 'img_offline'
            result=prepare_reports(root,'DU123',now,publish_image=publisher)
            path=Path(result['directory'])/'DAILY.json';report=json.loads(path.read_text());self.assertEqual(report['account']['positions']['value'],1)
            report.pop('render_version');path.write_text(json.dumps(report))
            prepare_reports(root,'DU123',now,publish_image=publisher);self.assertEqual(len(calls),2)
            html=(path.with_suffix('.html')).read_text();self.assertIn('Noto Sans CJK SC',html);self.assertIn('不是现金余额',html)
