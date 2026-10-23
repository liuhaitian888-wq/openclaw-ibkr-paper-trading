"""Observer failures cannot preserve stale success or authorize trading."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from ops.cloud import collect_paper_evidence as collector
from ops.cloud import healthchecks_sender as sender


class CloudObserverTests(unittest.TestCase):
    def setup_home(self, home):
        cfg=home/'.config/openclaw'; cfg.mkdir(parents=True)
        runtime=home/'.local/state/openclaw/runtime'; runtime.mkdir(parents=True)
        p=cfg/'paper-observer.json'; p.write_text(json.dumps({'expected_account':'DU1','symbols':['AAPL']}));p.chmod(0o600)
        return cfg,runtime

    def test_failed_readback_replaces_old_success_and_preserves_no_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);cfg,runtime=self.setup_home(home)
            (runtime/'paper-observer.latest.json').write_text('{"complete":true}')
            with patch.object(Path,'home',return_value=home),patch.object(collector,'probe',side_effect=TimeoutError),redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(),2)
            result=json.loads((runtime/'paper-observer.latest.json').read_text())
            self.assertFalse(result['complete']);self.assertFalse(result['grants_trading_permission'])
            self.assertEqual(result['status'],'AUTH_OR_CONNECTION_REQUIRED')
            self.assertFalse((runtime.parent/'production.json').exists())

    def test_invalid_account_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);cfg,runtime=self.setup_home(home)
            (cfg/'paper-observer.json').write_text('{"expected_account":"U1"}')
            with patch.object(Path,'home',return_value=home),patch.object(collector,'probe') as transport:
                with self.assertRaises(ValueError):collector.main()
            transport.assert_not_called()

    def test_mismatched_account_sends_failure_without_financial_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);cfg,runtime=self.setup_home(home)
            url='https://hc-ping.com/00000000-0000-0000-0000-000000000001'
            p=cfg/'healthchecks.json';p.write_text(json.dumps(dict(host_url=url,paper_api_url=url)));p.chmod(0o600)
            now=datetime.now(timezone.utc).isoformat()
            (runtime/'cloud-status.json').write_text(json.dumps(dict(observed_at=now,disk_free_fraction=.9)))
            (runtime/'paper-observer.latest.json').write_text(json.dumps(dict(observed_at=now,complete=True,environment='PAPER',account_id='DU2',positions=['must-stay-private'],resources={'connected_after_close':False})))
            opener=Mock();response=Mock(status=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False);opener.open.return_value=response
            with patch.object(Path,'home',return_value=home),patch.object(sender,'build_opener',return_value=opener):
                self.assertEqual(sender.main(),0)
            requests=[call.args[0] for call in opener.open.call_args_list]
            self.assertEqual([r.full_url for r in requests],[url,url+'/fail'])
            self.assertTrue(all(r.data is None for r in requests))

    def test_heartbeat_cannot_be_redirected_to_an_unapproved_recipient(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);cfg,runtime=self.setup_home(home)
            p=cfg/'healthchecks.json';p.write_text(json.dumps(dict(host_url='https://other.invalid/private',paper_api_url='https://other.invalid/private')));p.chmod(0o600)
            with patch.object(Path,'home',return_value=home),patch.object(sender,'build_opener') as transport:
                with self.assertRaises(ValueError):sender.main()
            transport.assert_not_called()

    def test_typed_identity_failure_is_not_mislabeled_as_generic_auth(self):
        from reporting.live_observation import PaperIdentityError
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); cfg,runtime=self.setup_home(home)
            with patch.object(Path,'home',return_value=home), patch.object(collector,'probe',side_effect=PaperIdentityError), redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(),2)
            result=json.loads((runtime/'paper-observer.latest.json').read_text())
            self.assertEqual(result['failure_class'],'IDENTITY_MISMATCH')
            self.assertFalse(result['grants_trading_permission'])
