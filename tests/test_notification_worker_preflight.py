from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from ops.cloud.feishu_alert_watch import claim_telegram,claimed_telegram_configuration
from reporting.incidents import IncidentStore
from reporting.notification_reconciliation import assess
from test_notification_center import CFG


class WorkerPreflightTests(unittest.TestCase):
    def test_bad_or_changed_config_cannot_claim_an_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'telegram.json';store=Mock()
            for content,mode in [('bad-json',0o600),(json.dumps(CFG),0o644),
                                 (json.dumps({**CFG,'expected_group_title':'deehub'}),0o600)]:
                p.write_text(content);p.chmod(mode)
                with self.assertRaises((ValueError,PermissionError,RuntimeError)):claim_telegram(store,p,CFG)
            store.claim.assert_not_called()

    def test_validated_config_claims_once_without_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'telegram.json';p.write_text(json.dumps(CFG));p.chmod(0o600)
            store=Mock();store.claim.return_value={'id':17}
            item,config=claim_telegram(store,p,CFG)
            self.assertEqual(item,{'id':17});self.assertEqual(config,CFG);store.claim.assert_called_once_with()

    def test_mixed_transport_preflight_has_positive_unsent_attempt_and_keeps_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'r.sqlite3')
            store.ingest('fixture','fixture',{'reason':'not sent','queued_at':store.clock()})
            item=store.claim();path=Path(tmp)/'absent-config.json'
            cfg,status=claimed_telegram_configuration(store,item,path)
            self.assertIsNone(cfg);self.assertEqual(status,'PENDING')
            self.assertEqual(assess(store,item['id'])['decision'],'PROVEN_UNSENT')
            with closing(store.connect()) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM notification_delivery').fetchone()[0],0)
                evidence=json.loads(c.execute('SELECT evidence FROM notification_attempt_events').fetchone()[0])
                self.assertFalse(evidence['transport_entered']);self.assertEqual(evidence['error_class'],'FileNotFoundError')
