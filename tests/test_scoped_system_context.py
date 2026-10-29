from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile,unittest
from reporting.recovery import RecoveryCoordinator
from ops.cloud.paper_safety_watch import read_system_safety

class ScopedSystemContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'home';self.root=self.home/'.local/state/openclaw';self.root.mkdir(parents=True)
        config=self.home/'.config/openclaw';config.mkdir(parents=True)
        (config/'paper.env').write_text('TRADING_KILL_SWITCH=false\nALLOW_PAPER_TRANSMIT=true\n')
        self.co=RecoveryCoordinator(self.root/'runtime/recovery.sqlite3')
        for name in ('RISK','CANONICAL_STATE'):self.co.observe(name,'HEALTHY',freshness='FRESH',reason='verified')
        self.manifest=dict(canonical_current_state_verified=True,safety=dict(ownership_verified=True,risk_allowed=True,risk_isolatable=True))
    def test_operator_pause_and_unknown_order_do_not_depend_on_symbol_count(self):
        facts=read_system_safety(self.root,self.manifest)
        self.assertTrue(facts['global_risk_verified']);self.assertTrue(facts['authoritative_state_verified'])
        self.assertTrue(facts['risk_isolatable']);self.assertFalse(facts['operator_paused'])
        self.co.begin_operation('unknown-order','order',{})
        self.assertFalse(read_system_safety(self.root,self.manifest)['risk_isolatable'])
        (self.root/'PAUSED').touch()
        self.assertTrue(read_system_safety(self.root,self.manifest)['operator_paused'])
    def test_unverified_or_failed_authoritative_risk_state_cannot_resume(self):
        self.co.observe('RISK','FAILED',freshness='STALE',reason='cannot value exposure')
        self.assertFalse(read_system_safety(self.root,self.manifest)['global_risk_verified'])
        (self.root/'runtime/recovery.sqlite3').unlink()
        facts=read_system_safety(self.root,self.manifest)
        self.assertFalse(facts['risk_isolatable']);self.assertFalse(facts['control_verified'])
