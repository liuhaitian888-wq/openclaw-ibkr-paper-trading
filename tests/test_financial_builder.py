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
