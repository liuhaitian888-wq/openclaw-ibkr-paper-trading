from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from reporting.agent_secretary import SecretaryArchive
from reporting.secretary_controls import login_status,tick_login,process_controls
from reporting.incidents import IncidentStore

class SecretaryControlTests(unittest.TestCase):
    def test_auth_success_requires_fresh_exact_full_reconciliation_and_notifies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();a=SecretaryArchive(root/'agent_secretary.sqlite3')
            a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/login_assist'})
            a.append('watch','der-secretary',origin='SYSTEM',kind='LOGIN_ASSIST',parent='owner',payload={'requested_at':1})
            with closing(sqlite3.connect(root/'runtime/recovery.sqlite3')) as c,c:
                c.execute('CREATE TABLE paper_safety_state(id INTEGER PRIMARY KEY,payload TEXT)')
                c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps({'connected':True,'identity':True,'upstream_connected':True,'dirty':False,'last_server_reply':100,'ends':['positions','orders','completed_orders','executions']}),))
            self.assertTrue(login_status(root,now=105)['verified']);self.assertFalse(login_status(root,now=111)['verified'])
            from unittest.mock import patch
            with patch('reporting.secretary_controls.time.time',return_value=105):tick_login(a,root);tick_login(a,root)
            store=IncidentStore(root/'runtime/recovery.sqlite3');self.assertIsNotNone(store.claim());self.assertIsNone(store.claim())
    def test_gate_command_bypasses_model_and_does_not_start_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3')
            a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/gate'})
            from unittest.mock import patch
            with patch('reporting.secretary_controls.subprocess.run') as run:
                self.assertEqual(process_controls(a,root,{'bot_username':'fixture'}),[])
            run.assert_not_called()
            with closing(a.connect()) as c:self.assertEqual(c.execute('SELECT model,state FROM secretary_runs').fetchone(),('PYTHON_CONTROL','SUCCEEDED'))
