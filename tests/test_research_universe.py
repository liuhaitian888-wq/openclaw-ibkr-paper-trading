from pathlib import Path
import tempfile,unittest,json
from reporting.agent_secretary import SecretaryArchive
from reporting.research_universe import select,effective_symbols

class ResearchUniverseTests(unittest.TestCase):
    def test_agent_research_selection_does_not_remove_verified_positions_or_grant_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3');a.append('instruction','der-secretary',origin='USER',kind='INSTRUCTION',payload={})
            result=select(a,root,{'symbols':['MSFT'],'reasons':{'MSFT':'earnings test'}},run='run',instruction='instruction',step=1)
            self.assertFalse(result['selection']['execution_universe_changed'])
            self.assertEqual(effective_symbols(root,{}, {'positions':{'PFE':8}}),['PFE','MSFT'])
            self.assertEqual(effective_symbols(root,{'baseline_position_symbols':['PFE']},{}),['PFE','MSFT'])
            self.assertFalse((root/'production.json').exists())
    def test_no_reason_or_unbounded_universe_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'a.sqlite3')
            with self.assertRaises(ValueError):select(a,root,{'symbols':['AAPL'],'reasons':{}},run='r',instruction='missing',step=1)
