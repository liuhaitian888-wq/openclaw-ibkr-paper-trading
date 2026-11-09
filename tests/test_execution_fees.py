from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import json,sqlite3,sys,tempfile,unittest
from trading.paper_safety_monitor import PaperSafetyMonitor,ACCOUNT
from trading.paper_safety_client import PaperSafetyClient


class ExecutionFeeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.now=1000
        self.monitor=PaperSafetyMonitor(root/'audit.sqlite3',root/'recovery.sqlite3',symbols=['PFE'],required_bars=1,clock=lambda:self.now)
        self.client=PaperSafetyClient(self.monitor,['PFE'])

    def test_native_fee_before_execution_is_retained_but_account_binding_waits(self):
        report=NS(execId='native-exec',currency='USD',commissionAndFees=1.25)
        self.client.commissionAndFeesReport(report)
        with closing(self.monitor.audit._connect()) as c:self.assertEqual(c.execute('SELECT account FROM execution_fee_facts').fetchone()[0],'')
        self.monitor.begin([ACCOUNT]);self.monitor.execution(dict(exec_id='native-exec',account=ACCOUNT,order_id=11,perm_id=9911,order_ref='intent',symbol='PFE',side='BOT',shares=1,price=100,time='now',con_id=1,currency='USD',sec_type='STK'))
        self.client.commissionAndFeesReport(report)
        with closing(self.monitor.audit._connect()) as c:
            row=c.execute('SELECT account,amount,revision FROM execution_fee_facts').fetchone()
            self.assertEqual(row[:],(ACCOUNT,'1.25',2));self.assertEqual(c.execute('SELECT count(*) FROM execution_fee_events').fetchone()[0],2)
        self.now+=1;self.client.commissionAndFeesReport(NS(execId='native-exec',currency='USD',commissionAndFees=2))
        self.now+=1;self.client.commissionAndFeesReport(report)
        with closing(self.monitor.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT revision FROM execution_fee_facts').fetchone()[0],4)
            self.assertEqual(c.execute('SELECT count(*) FROM execution_fee_events').fetchone()[0],4)

    def test_unset_commission_is_not_an_explicit_zero_fee(self):
        self.client.commissionReport(NS(execId='unset',currency='USD',commission=sys.float_info.max))
        with closing(self.monitor.audit._connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM execution_fee_facts').fetchone()[0],0)
        self.client.commissionReport(NS(execId='zero-native',currency='USD',commission=0))
        with closing(self.monitor.audit._connect()) as c:self.assertIsNone(c.execute("SELECT amount FROM execution_fee_facts WHERE exec_id='zero-native'").fetchone())

    def test_fee_persistence_failure_invalidates_current_safety_evidence(self):
        self.monitor.begin([ACCOUNT])
        with patch.object(self.monitor.audit,'record_execution_fee',side_effect=sqlite3.OperationalError('fixture database unavailable')):
            self.client.commissionAndFeesReport(NS(execId='known',currency='USD',commissionAndFees=1))
        self.assertFalse(self.monitor.state['connected']);self.assertEqual(self.monitor.state['fault'],'AUDIT_FEE_PERSISTENCE_FAILED')
        self.assertFalse(self.monitor.snapshot()['entries_ready'])

    def test_missing_protobuf_fee_default_is_not_native_zero(self):
        from ibapi.wrapper import EWrapper
        message_type=EWrapper.commissionAndFeesReportProtoBuf.__annotations__['commissionAndFeesReportProto']
        message=message_type(execId='missing-proto',currency='USD')
        self.client.commissionAndFeesReportProtoBuf(message)
        self.client.commissionAndFeesReport(NS(execId='missing-proto',currency='USD',commissionAndFees=0))
        with closing(self.monitor.audit._connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM execution_fee_facts').fetchone()[0],0)
        message=message_type(execId='explicit-proto-zero',currency='USD',commissionAndFees=0)
        self.client.commissionAndFeesReportProtoBuf(message)
        self.client.commissionAndFeesReport(NS(execId='explicit-proto-zero',currency='USD',commissionAndFees=0))
        with closing(self.monitor.audit._connect()) as c:
            self.assertEqual(c.execute('SELECT amount,source FROM execution_fee_facts').fetchone()[:],('0','commissionAndFeesReportProtoBuf'))
