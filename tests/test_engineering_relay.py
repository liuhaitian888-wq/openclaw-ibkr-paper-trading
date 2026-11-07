from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive
from reporting.engineering_relay import propose,proposals
from reporting.secretary_queue import CONVERSATION

class EngineeringRelayTests(unittest.TestCase):
    def test_duplicate_proposal_is_shared_without_authority_and_engineer_status_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=SecretaryArchive(Path(tmp)/'a.sqlite3')
            for key in ('one','two'):a.append(key,CONVERSATION,origin='USER',kind='CHAT_INSTRUCTION',payload={'text':'review infrastructure'})
            req={'title':'Check fonts','observation':'CJK glyphs unavailable','suggested_change':'Install reviewed CJK font','evidence':['source:fc-match']}
            p=propose(a,req,instruction='one');again=propose(a,req,instruction='two');self.assertEqual(p['id'],again['id']);self.assertEqual(again['state'],'EXISTING_PROPOSAL')
            items=proposals(a);self.assertFalse(items['automatic_deployment']);self.assertFalse(items['desktop_chat_wakeup_connected']);self.assertEqual(len(items['items']),1)
            self.assertEqual(items['items'][0]['engineering_status']['state'],'PROPOSED_NOT_EXECUTED')
            a.append(p['id']+':status:1',CONVERSATION,origin='SYSTEM',kind='ENGINEERING_STATUS',parent=p['id'],payload={'state':'RECEIVED','source':'Codex engineering operator'})
            self.assertEqual(proposals(a)['items'][0]['engineering_status']['state'],'RECEIVED')
            with self.assertRaises(ValueError):propose(a,{**req,'evidence':[]},instruction='one')
