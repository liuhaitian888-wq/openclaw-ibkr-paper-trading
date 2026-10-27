from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reporting.paper_signal_report import build_report, write_report, publish_report, session_state
from trading.market_data import Quote
from trading.strategy_modules import ConservativeTrendModule


NOW = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)
ACCOUNT = 'DU123456'


def observation(at, price=100):
    return dict(observed_at=at.isoformat(), status='READBACK_COMPLETE', complete=True,
                source='REAL_IBKR', environment='PAPER', account_id=ACCOUNT,
                resources=dict(worker_stopped=True, reader_stopped=True, connected_after_close=False),
                quotes={'AAPL': dict(data_type=1, bid=price, ask=price + .02,
                                     received_at=at.isoformat())})


class PaperSignalReportTests(unittest.TestCase):
    def test_session_codes_distinguish_competition_connectivity_and_recovery(self):
        for args, expected in (([10197, 'competing'], 'MARKET_DATA_COMPETITION'),
                               ([1793115600000, 10197, 'competing', ''], 'MARKET_DATA_COMPETITION'),
                               ([1793115600000, 1100, 'lost', ''], 'BROKER_CONNECTION_LOST'),
                               ([1101, 'restored'], 'READBACK_AND_RESUBSCRIBE_REQUIRED')):
            item=observation(NOW);item['raw_errors']=[dict(raw_callback_arguments=args)]
            self.assertEqual(session_state(item, ACCOUNT, ['AAPL'])['state'], expected)
            r=build_report([item],ACCOUNT,['AAPL'],NOW)
            self.assertIsNone(r['symbols']['AAPL']['signal'])
        item=observation(NOW);item['account_id']='U123'
        self.assertEqual(session_state(item,ACCOUNT,['AAPL'])['state'],'IDENTITY_UNVERIFIED')
        item=observation(NOW);item['quotes']['AAPL']['data_type']=3
        self.assertEqual(session_state(item,ACCOUNT,['AAPL'])['state'],'MARKET_DATA_UNAVAILABLE')

    def test_timeline_is_rebuilt_without_replay_or_claiming_exact_outage_start(self):
        good=observation(NOW-timedelta(minutes=10))
        failed=dict(observed_at=(NOW-timedelta(minutes=5)).isoformat(),status='AUTH_OR_CONNECTION_REQUIRED',error_type='TimeoutError')
        recovered=observation(NOW)
        r=build_report([good,failed,recovered,recovered],ACCOUNT,['AAPL'],NOW)
        events=r['session_history']['transitions']
        self.assertEqual([e['state'] for e in events],['PAPER_DATA_VERIFIED','AUTH_OR_CONNECTION_UNVERIFIED','PAPER_DATA_VERIFIED'])
        self.assertEqual(events[-1]['transition'],'OBSERVED_RECOVERY_RECONCILIATION_NOT_APPROVED')
        self.assertEqual(events[-1]['observed_fault_span_seconds'],300)
        self.assertFalse(r['session_history']['exact_outage_duration_known'])
        self.assertFalse(r['grants_trading_permission'])
        self.assertEqual(r['symbols']['AAPL']['sample_count'],1)

    def test_observation_gap_is_recorded_separately_not_called_login_loss(self):
        r=build_report([observation(NOW-timedelta(minutes=30)),observation(NOW)],ACCOUNT,['AAPL'],NOW)
        events=r['session_history']['transitions']
        self.assertIn('OBSERVATION_GAP',[e['state'] for e in events])
        self.assertTrue(all('phone' not in str(e).lower() for e in events))

    def test_existing_module_evaluates_without_simulated_fill_or_order_transport(self):
        samples=[observation(NOW-timedelta(minutes=5*(4-i)),100+i) for i in range(5)]
        samples[-1]['positions']=[dict(symbol='AAPL',position='17',avgCost=90)]
        with patch.object(Quote,'age_ms',return_value=0), patch.object(ConservativeTrendModule,'record_order_decision',side_effect=AssertionError('no fills')):
            r=build_report(samples,ACCOUNT,['AAPL'],NOW)
        model=r['symbols']['AAPL']['existing_model']
        self.assertEqual(model['name'],'classic_conservative_trend')
        self.assertEqual(model['decision']['action'],'BUY')
        self.assertFalse(model['execution_authorized'])
        self.assertFalse(model['configuration_approved'])
        self.assertEqual(model['broker_exposure_quantity'],'17')
        self.assertFalse(model['broker_position_adopted_as_strategy_owned'])
        self.assertEqual(r['orders_submitted'],0)

    def test_report_model_reference_config_matches_existing_cli_defaults(self):
        from scripts.run_pool_strategy_module import parse_args
        with patch('sys.argv',['run_pool_strategy_module.py']): args=parse_args()
        r=build_report([observation(NOW)],ACCOUNT,['AAPL'],NOW)
        cfg=r['symbols']['AAPL']['existing_model']['configuration']
        for key in ('fast_window','slow_window','profit_target_pct','stop_loss_pct','min_gap_pct','cooldown_steps'):
            self.assertEqual(cfg[key],getattr(args,key))

    def test_fault_and_corrupt_source_cannot_leave_old_model_proposals(self):
        item=observation(NOW);item['raw_errors']=[dict(raw_callback_arguments=[10197,'competing'])]
        with patch.object(ConservativeTrendModule,'evaluate',side_effect=AssertionError('fault must block model')):
            r=build_report([item],ACCOUNT,['AAPL'],NOW)
        self.assertIsNone(r['symbols']['AAPL']['existing_model']['decision'])

    def test_real_samples_reuse_engine_but_never_grant_trading_permission(self):
        samples = [observation(NOW-timedelta(minutes=5*(5-i)), 100+i) for i in range(6)]
        report = build_report(samples, ACCOUNT, ['AAPL'], NOW)
        self.assertEqual(report['status'], 'SHADOW_READY')
        self.assertEqual(report['symbols']['AAPL']['signal'], 'ENTER_LONG')
        self.assertEqual(report['symbols']['AAPL']['sample_count'], 6)
        self.assertEqual(report['sampling'], '5-minute bid/ask midpoint samples; not OHLC or complete L1')
        self.assertFalse(report['grants_trading_permission'])
        self.assertEqual(report['orders_submitted'], 0)

    def test_latest_failure_or_stale_success_never_reuses_old_signal(self):
        good = observation(NOW-timedelta(minutes=15))
        for latest in (good, dict(observed_at=NOW.isoformat(), status='AUTH_OR_CONNECTION_REQUIRED')):
            r = build_report([good, latest], ACCOUNT, ['AAPL'], NOW)
            self.assertNotEqual(r['status'], 'SHADOW_READY')
            self.assertIsNone(r['symbols']['AAPL']['signal'])

    def test_rejects_wrong_identity_missing_close_and_bad_quotes(self):
        changes = [dict(account_id='U123456'), dict(account_id='DUOTHER'),
                   dict(environment='LIVE'), dict(complete=False), dict(resources={}),
                   dict(source='SIMULATED')]
        for change in changes:
            item = observation(NOW); item.update(change)
            r = build_report([item], ACCOUNT, ['AAPL'], NOW)
            self.assertEqual(r['symbols']['AAPL']['sample_count'], 0)
        for change in (dict(data_type=3), dict(bid=float('nan')), dict(ask=90),
                       dict(received_at=(NOW-timedelta(minutes=10)).isoformat()), dict(bid=True)):
            item = observation(NOW); item['quotes']['AAPL'].update(change)
            r = build_report([item], ACCOUNT, ['AAPL'], NOW)
            self.assertEqual(r['symbols']['AAPL']['sample_count'], 0)

    def test_duplicates_same_slot_do_not_warm_up_and_gap_resets_history(self):
        r = build_report([observation(NOW+timedelta(seconds=i)) for i in range(5)],
                         ACCOUNT, ['AAPL'], NOW+timedelta(seconds=5))
        self.assertEqual(r['symbols']['AAPL']['sample_count'], 1)
        samples = [observation(NOW-timedelta(minutes=40)), observation(NOW-timedelta(minutes=35)),
                   observation(NOW)]
        r = build_report(samples, ACCOUNT, ['AAPL'], NOW)
        self.assertEqual(r['symbols']['AAPL']['sample_count'], 1)
        self.assertEqual(r['symbols']['AAPL']['signal'], 'WARMING_UP')

    def test_failure_inside_same_slot_cannot_be_hidden_by_prior_success(self):
        bad = dict(observed_at=(NOW+timedelta(seconds=10)).isoformat(), status='AUTH_OR_CONNECTION_REQUIRED')
        r = build_report([observation(NOW), bad], ACCOUNT, ['AAPL'], NOW+timedelta(seconds=11))
        self.assertIsNone(r['symbols']['AAPL']['signal'])

    def test_future_timestamp_is_not_current_data(self):
        r = build_report([observation(NOW+timedelta(minutes=10))], ACCOUNT, ['AAPL'], NOW)
        self.assertEqual(r['status'], 'INVALID_TIME')
        self.assertIsNone(r['symbols']['AAPL']['signal'])

    def test_report_private_files_and_no_trading_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root/'observations/2026-10-27/150000.json'
            p.parent.mkdir(parents=True); p.write_text(json.dumps(observation(NOW)))
            config = dict(expected_account=ACCOUNT, symbols=['AAPL'])
            with patch('socket.socket.connect', side_effect=AssertionError('no network')):
                r = write_report(root, config, now=NOW)
            output = root/'reports/paper_shadow/latest.json'
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(root.rglob('*.sqlite3')))
            self.assertEqual(r['status'], 'WARMING_UP')
            self.assertIn('非交易指令', (output.parent/'latest.md').read_text())
            self.assertEqual(r['universe_reference']['status'],'REFERENCE_ONLY_NOT_APPROVED')
            self.assertEqual(len(r['universe_reference']['sha256']),64)
            self.assertEqual([x['symbol'] for x in r['universe_reference']['records']],['AAPL'])

    def test_invalid_file_cannot_fall_back_to_older_success_and_publish_is_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); day=root/'observations/2026-10-27'; day.mkdir(parents=True)
            (day/'145500.json').write_text(json.dumps(observation(NOW-timedelta(minutes=5))))
            (day/'150000.json').write_text('{broken')
            r=write_report(root, dict(expected_account=ACCOUNT, symbols=['AAPL']), now=NOW)
            self.assertEqual(r['status'], 'SOURCE_FILE_INVALID')
            with patch('reporting.paper_signal_report.write_report', side_effect=OSError('full')):
                self.assertEqual(publish_report(root, {})['status'], 'REPORT_WRITE_FAILED')


if __name__ == '__main__':
    unittest.main()
