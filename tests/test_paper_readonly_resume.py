from contextlib import closing
from datetime import datetime,timezone
import json,os,unittest
from unittest.mock import patch
from trading.paper_readonly_resume import claim_resume,confirm_resume,retain_failed_resume,KIND
from trading.sqlite_event_store import SQLiteEventStore
from tests import test_native_cash_owner as fixtures


class PaperReadonlyResumeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeCashOwnerTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.monitor=self.fixture.monitor;self.root=self.fixture.root.resolve();self.now=self.fixture.now
        SQLiteEventStore(self.monitor.audit._path)
        self.monitor.state['connection_recovery'].update(attempts=4,not_before=self.now-1,gateway_generation='same-gateway')
        self.actual=dict(commit='a'*40,branch='codex/paper',code_root='/approved',state_root=str(self.root))
        self.manifest=dict(self.actual,monitoring_approved=True,environment='PAPER',grants_trading_permission=False)
        self.scope=dict(self.actual,approved=True,environment='PAPER',account='DUQ503649',service='paper-safety',
            identity='paper-readonly-storage-recovery-test-v1',gateway_generation='same-gateway',prior_attempts=4,
            max_connections=1,issued_at=datetime.fromtimestamp(self.now,timezone.utc).isoformat(),
            expires_at=datetime.fromtimestamp(self.now+300,timezone.utc).isoformat(),grants_trading_permission=False)
        (self.root/'runtime/gateway-automater-deployment.json').write_text(json.dumps(dict(self.actual,approved=True,environment='PAPER',grants_trading_permission=False)))
        self.path=self.root/'runtime/paper-readonly-resume-scope.json';self.save()

    def save(self):self.path.write_text(json.dumps(self.scope));self.path.chmod(0o600)
    def claim(self,gateway='same-gateway',listening=True):
        with patch('trading.paper_readonly_resume.context',return_value=self.actual):
            return claim_resume(self.monitor,self.root,self.manifest,gateway,api_listening=listening,clock=lambda:self.now)

    def test_scope_claim_is_durable_once_and_preserves_four_original_attempts(self):
        resume=self.claim();self.assertIsNotNone(resume);self.assertIsNone(self.claim())
        self.assertEqual(self.monitor.state['connection_recovery']['attempts'],4)
        with closing(self.monitor.coordinator.connect()) as c:
            self.assertEqual(c.execute('SELECT kind,status FROM operation_attempts WHERE identity=?',(resume['identity'],)).fetchone(),(KIND,'STARTED'))
        resume['transport_started']=True;retain_failed_resume(self.monitor,resume)
        self.assertIsNone(self.claim())
        with closing(self.monitor.coordinator.connect()) as c:self.assertEqual(c.execute('SELECT status FROM operation_attempts').fetchone()[0],'UNKNOWN')

    def test_expiry_gateway_backoff_or_approval_mismatch_never_claims(self):
        self.assertIsNone(self.claim(gateway='changed'))
        self.assertIsNone(self.claim(listening=False))
        self.scope['expires_at']=datetime.fromtimestamp(self.now-1,timezone.utc).isoformat();self.save()
        self.assertIsNone(self.claim())
        with closing(self.monitor.coordinator.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM operation_attempts').fetchone()[0],0)

    def test_unknown_readonly_scope_cannot_be_bypassed_by_changing_identity(self):
        first=self.claim();first['transport_started']=True;retain_failed_resume(self.monitor,first)
        self.scope['identity']='paper-readonly-storage-recovery-test-v2';self.save()
        self.assertIsNone(self.claim())

    def test_confirmed_native_readback_does_not_reset_four_attempts_or_grant_trade(self):
        resume=self.claim();self.assertIsNotNone(resume)
        self.assertTrue(confirm_resume(self.monitor,resume,self.now-61,'same-gateway'))
        self.assertEqual(self.monitor.state['connection_recovery']['attempts'],4)
        retain_failed_resume(self.monitor,resume)
        with closing(self.monitor.coordinator.connect()) as c:
            self.assertEqual(c.execute('SELECT status FROM operation_attempts').fetchone()[0],'CONFIRMED')
        self.assertFalse(json.loads(self.path.read_text())['grants_trading_permission'])

    def test_preview_has_no_claim_and_expiry_is_rechecked_before_transport(self):
        with patch('trading.paper_readonly_resume.context',return_value=self.actual):
            candidate=claim_resume(self.monitor,self.root,self.manifest,'same-gateway',api_listening=True,clock=lambda:self.now,claim=False)
        self.assertTrue(candidate['eligible'])
        with closing(self.monitor.coordinator.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM operation_attempts').fetchone()[0],0)
        self.now+=301
        self.assertIsNone(self.claim())
