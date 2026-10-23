"""Regression tests for the former non-Mac path production-guard exemption."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import trading.production_guard as guard


class CloudPaperSafetyTests(unittest.TestCase):
    def test_changed_code_path_never_bypasses_order_gate(self):
        transport=Mock()
        @guard.guarded_broker_operation
        def submit(order_ref):
            return transport(order_ref)
        with (patch('trading.production_paths.CODE_ROOT',Path('/tmp/other')),
              patch('trading.production_paths.PRODUCTION_WORKSPACE',Path('/opt/openclaw/app')),
              patch.object(guard,'require_module_gate',side_effect=PermissionError('blocked')) as gate):
            with self.assertRaisesRegex(PermissionError,'blocked'):submit('stable-intent')
        gate.assert_called_once_with('ORDER_SUBMISSION_ALLOWED',duplicate_or_unknown=False)
        transport.assert_not_called()

    def test_account_check_is_not_skipped_in_a_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(guard,'STATE_ROOT',root):
                with self.assertRaises(PermissionError):guard.require_connected_account(['DU1'])
                (root/'production.json').write_text(json.dumps({'ready':True,'account':'DU1','environment':'PAPER'}))
                guard.require_connected_account(['DU1'])
                for accounts in (['U1'],['DU2'],[],['DU1','DU2']):
                    with self.assertRaises(PermissionError):guard.require_connected_account(accounts)

    def test_live_environment_is_rejected_even_with_matching_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'production.json').write_text(json.dumps({'ready':True,'account':'DU1','environment':'LIVE'}))
            with patch.object(guard,'STATE_ROOT',root):
                with self.assertRaises(PermissionError):guard.require_connected_account(['DU1'])
