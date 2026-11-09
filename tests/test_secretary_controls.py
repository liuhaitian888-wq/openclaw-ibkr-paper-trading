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
    def test_plain_chinese_gate_command_immediately_updates_python_caps(self):
        from reporting.telegram_gate import current
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3')
            a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/gate_set 单笔金额 150'})
            process_controls(a,root,{'bot_username':'fixture'},{'numeric_gate_controls_approved':True})
            self.assertEqual(current(root)['settings']['max_order_value'],'150')
            with closing(a.connect()) as c:self.assertEqual(c.execute('SELECT model FROM secretary_runs').fetchone()[0],'PYTHON_CONTROL')
    def test_focus_is_bound_to_user_and_injected_into_future_autonomous_task(self):
        from reporting.secretary_queue import initialize,autonomous
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3');initialize(a)
            a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/focus 研究持仓财报，缺数据就证伪'})
            process_controls(a,root,{'bot_username':'fixture'});autonomous(a,now=100000)
            with closing(a.connect()) as c:payload=json.loads(c.execute("SELECT payload FROM secretary_events WHERE kind='AUTONOMOUS_INSTRUCTION'").fetchone()[0])
            self.assertIn('持仓财报',payload['standing_focus']['text']);self.assertEqual(payload['standing_focus']['source_instruction'],'owner')
    def test_short_english_risk_gate_is_direct_python_and_not_an_order(self):
        from reporting.telegram_gate import current
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3')
            a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/omax 125'})
            process_controls(a,root,{'bot_username':'fixture'},{'numeric_gate_controls_approved':True})
            self.assertEqual(current(root)['settings']['max_order_value'],'125')
            self.assertFalse((root/'production.json').exists())

    def test_ready_and_holdings_are_deterministic_owner_controls(self):
        from unittest.mock import patch
        for command in ('/ready','/holdings'):
            with self.subTest(command=command),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3')
                a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':command})
                with patch('reporting.paper_readiness.collect',return_value={'fixture':True}) as read,patch('reporting.paper_readiness.message',return_value='Read-only status'):
                    process_controls(a,root,{'bot_username':'fixture'})
                read.assert_called_once_with(root)
                with closing(a.connect()) as c:self.assertEqual(c.execute('SELECT model FROM secretary_runs').fetchone()[0],'PYTHON_CONTROL')
                self.assertFalse((root/'production.json').exists())

    def test_market_weekly_and_codex_controls_no_shell_or_model(self):
        from reporting.secretary_controls import menu_commands
        self.assertTrue({'hours','weekly','codex'}.issubset({x[0] for x in menu_commands()}))
        from unittest.mock import patch
        for i,command in enumerate(('/hours','/weekly','/codex 修复有证据的工程问题')):
            with self.subTest(command=command),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);a=SecretaryArchive(root/'agent.sqlite3')
                a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':command})
                with patch('reporting.secretary_controls.subprocess.run') as run:
                    process_controls(a,root,{'bot_username':'fixture'})
                run.assert_not_called()
                with closing(a.connect()) as c:
                    self.assertEqual(c.execute('SELECT model,state FROM secretary_runs').fetchone(),('PYTHON_CONTROL','SUCCEEDED'))
                    if command.startswith('/codex'):
                        row=c.execute("SELECT origin,parent,payload FROM secretary_events WHERE kind='ENGINEERING_HANDOFF'").fetchone()
                        self.assertEqual(row[:2],('TOOL','owner'))
                        self.assertEqual(json.loads(row[2])['state'],'ARCHIVED_NOT_ACCEPTED')
                self.assertFalse((root/'production.json').exists())
