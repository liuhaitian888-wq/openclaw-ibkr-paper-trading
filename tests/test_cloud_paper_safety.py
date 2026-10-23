"""Regression tests for the former non-Mac path production-guard exemption."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import trading.production_guard as guard
from reporting.recovery import RecoveryCoordinator


class CloudPaperSafetyTests(unittest.TestCase):
    def test_new_intent_key_cannot_bypass_unknown_order_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'recovery.sqlite3';store=RecoveryCoordinator(path)
            self.assertTrue(store.begin_operation('first','order',{}))
            store.finish_operation('first','UNKNOWN')
            restarted=RecoveryCoordinator(path)
            self.assertFalse(restarted.begin_operation('different-key','order',{}))
            self.assertTrue(restarted.begin_operation('notify','delivery',{}))
            # Only an explicit reconciliation result permits a new order.
            restarted.finish_operation('first','CONFIRMED')
            self.assertTrue(restarted.begin_operation('different-key','order',{}))
            self.assertFalse(restarted.begin_operation('first','order',{}))

    def test_concurrent_distinct_orders_cannot_both_reserve_before_ack(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'recovery.sqlite3'
            stores=[RecoveryCoordinator(path),RecoveryCoordinator(path)];barrier=Barrier(2)
            def reserve(i):
                barrier.wait(timeout=5)
                return stores[i].begin_operation('intent-'+str(i),'order',{})
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(reserve,range(2)))
            self.assertEqual(sorted(results),[False,True])

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
