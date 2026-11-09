import threading
import unittest
from trading.native_pnl_collector import NativePnLCollector


class NativePnLCollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = 1794257000.
        self.calls, self.receipts = [], []
        self.allowed = True
        self.sequence = 800000000
        owner = self
        class Client:
            accounts = ['DUQ503649']
            def isConnected(self): return True
            def reqPnL(self, *args): owner.calls.append(('request', *args))
            def cancelPnL(self, request): owner.calls.append(('cancel', request))
        self.client = Client()
        self.actor = NativePnLCollector(self.client, account='DUQ503649',
            connection_generation='current', admitted=lambda: self.allowed,
            allocate_request_id=self.allocate, publish=self.receipts.append,
            clock=lambda: self.now, monotonic=lambda: self.now)
    def allocate(self):
        self.sequence += 1
        return self.sequence
    def start(self):
        self.actor.poll()
        return self.calls[-1][1]
    def test_exact_owned_callback_cancels_before_publishing_real_zero(self):
        request = self.start()
        def publish(receipt):
            self.assertEqual(self.calls[-1], ('cancel', request))
            self.receipts.append(receipt)
        self.actor.publish = publish
        self.actor.value(request + 1, 0, 0, 0)
        self.assertEqual(self.receipts, [])
        self.actor.value(request, 0, -123.5, 12)
        self.assertEqual(self.receipts[0]['daily'], 0)
        self.assertFalse(self.receipts[0]['grants_trading_permission'])
        self.actor.value(request, 1, 2, 3)
        self.assertEqual(len(self.receipts), 1)
    def test_missing_sentinel_bool_and_nonfinite_do_not_become_zero(self):
        for bad in (None, True, float('nan'), float('inf'), 1.7976931348623157e308, 1 << 4096):
            self.setUp()
            request = self.start()
            self.actor.value(request, bad, 0, 0)
            self.assertEqual(self.receipts, [])
            self.assertEqual(self.calls[-1], ('cancel', request))
    def test_timeout_and_cancel_failure_forbid_duplicate_subscription(self):
        request = self.start()
        self.now += 8
        with self.assertRaises(RuntimeError): self.actor.poll()
        self.assertEqual(self.calls[-1], ('cancel', request))
        with self.assertRaises(RuntimeError): self.actor.poll()
        self.setUp()
        request = self.start()
        def fail(request): raise OSError('fixture cancel unavailable')
        self.client.cancelPnL = fail
        self.actor.value(request, 1, 2, 3)
        self.assertEqual(self.receipts, [])
        with self.assertRaises(RuntimeError): self.actor.poll()
    def test_changed_identity_or_admission_closes_only_owned_request(self):
        request = self.start()
        self.allowed = False
        self.actor.value(request, 1, 2, 3)
        self.assertEqual(self.receipts, [])
        self.actor.poll()
        self.assertEqual(self.calls, [('request', request, 'DUQ503649', ''), ('cancel', request)])
    def test_send_failure_cancels_reserved_identity_before_reconciliation(self):
        def fail(*args):
            self.calls.append(('request', *args))
            raise OSError('fixture transport unavailable')
        self.client.reqPnL = fail
        with self.assertRaises(RuntimeError): self.actor.poll()
        self.assertEqual(self.calls, [('request', 800000001, 'DUQ503649', ''), ('cancel', 800000001)])
        with self.assertRaises(RuntimeError): self.actor.poll()
    def test_consumer_failure_stops_actor_without_poisoning_sdk(self):
        request = self.start()
        def fail(receipt): raise OSError('fixture local persistence unavailable')
        self.actor.publish = fail
        self.actor.value(request, 1, 2, 3)
        self.now += 30
        self.actor.poll()
        self.assertTrue(self.actor.closed)
        self.assertEqual(self.actor.failure_reason,'NATIVE_PNL_PUBLICATION_FAILED')
        self.assertFalse(self.actor.poisoned)
        self.assertEqual(len(self.calls), 2)
    def test_repeated_cycles_and_shutdown_have_no_additional_worker(self):
        threads = threading.active_count()
        for _ in range(200):
            request = self.start()
            self.actor.poll()
            self.actor.value(request, 1, 2, 3)
            self.now += 30
        self.actor.close()
        self.actor.poll()
        self.assertEqual(len(self.receipts), 200)
        self.assertEqual(len(self.calls), 400)
        self.assertEqual(threading.active_count(), threads)
