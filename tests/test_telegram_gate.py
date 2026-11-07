from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.telegram_gate import apply,current,template,DEFAULT
from trading.risk import RiskEngine,RiskLimits
from trading.models import TradeProposal

class TelegramGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.a=SecretaryArchive(self.root/'agent.sqlite3')
        for key in ('owner1','owner2'):self.a.append(key,'der',origin='USER',kind='CONTROL_INSTRUCTION',payload={})
    def req(self,**values):return {'revision':0,'settings':{**DEFAULT,**values}}
    def test_compare_and_swap_and_content_identity(self):
        result=apply(self.a,self.root,'owner1',self.req(max_order_value='150'))
        self.assertEqual(result['revision'],1);self.assertEqual(current(self.root)['settings']['max_order_value'],'150')
        self.assertEqual(apply(self.a,self.root,'owner1',self.req(max_order_value='150')),result)
        with self.assertRaises(ValueError):apply(self.a,self.root,'owner2',self.req(max_order_value='140'))
        self.assertIn('/gate_apply',template(self.root))
    def test_no_model_or_extra_privileged_fields(self):
        self.a.append('model','der',origin='MODEL',kind='CONTROL_INSTRUCTION',payload={})
        with self.assertRaises(PermissionError):apply(self.a,self.root,'model',self.req())
        for value in (float('nan'),float('inf'),True,-1):
            with self.subTest(value=value),self.assertRaises(ValueError):apply(self.a,self.root,'owner1',self.req(max_order_value=value))
        request=self.req();request['settings']['approved']=True
        with self.assertRaises(ValueError):apply(self.a,self.root,'owner1',request)
    def test_risk_engine_reloads_caps_without_restarting_and_cannot_loosen_original(self):
        engine=RiskEngine(RiskLimits(True,frozenset({'AAPL'}),1,200,10))
        proposal=TradeProposal('AAPL','BUY',1,180,175)
        with patch('trading.production_paths.STATE_ROOT',self.root):
            self.assertTrue(engine.validate(proposal).approved)
            apply(self.a,self.root,'owner1',self.req(max_order_value='150'))
            self.assertFalse(engine.validate(proposal).approved)
            apply(self.a,self.root,'owner2',{'revision':1,'settings':{**DEFAULT,'max_order_value':'500'}})
            self.assertTrue(engine.validate(proposal).approved)
            self.assertFalse(engine.validate(TradeProposal('AAPL','BUY',1,210,205)).approved)
    def test_corrupt_controls_fail_closed_and_pause_files_untouched(self):
        (self.root/'runtime').mkdir(exist_ok=True);(self.root/'PAUSED').write_text('preserved')
        (self.root/'runtime/risk-controls.json').write_text('{broken')
        with patch('trading.production_paths.STATE_ROOT',self.root):
            self.assertFalse(RiskEngine(RiskLimits(True,frozenset({'AAPL'}),1,200,10)).validate(TradeProposal('AAPL','BUY',1,180,175)).approved)
        self.assertEqual((self.root/'PAUSED').read_text(),'preserved')
    def test_previously_activated_missing_caps_fail_closed_and_reconcile_from_archive(self):
        from reporting.telegram_gate import reconcile
        apply(self.a,self.root,'owner1',self.req(max_order_value='150'))
        (self.root/'runtime/risk-controls.json').unlink()
        with self.assertRaises(ValueError):current(self.root)
        reconcile(self.a,self.root)
        self.assertEqual(current(self.root)['settings']['max_order_value'],'150')
