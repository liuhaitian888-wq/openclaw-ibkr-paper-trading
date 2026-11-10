from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from reporting.health import MODULE_DEPENDENCIES,dependency_registry,resolve_modules
from trading.native_cash_publication import publish_native_cashbook
from trading.paper_safety_monitor import PaperSafetyMonitor,ACCOUNT
from trading.paper_safety_client import PaperSafetyClient
from tests import test_native_cash_collector as cash_fixtures

class NativeCashOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'runtime').mkdir();self.now=1794257000.
        self.monitor=PaperSafetyMonitor(self.root/'trading_audit.sqlite3',self.root/'runtime/recovery.sqlite3',symbols=['PFE'],required_bars=1,clock=lambda:self.now)
        self.client=PaperSafetyClient(self.monitor,['PFE'],cashbook_publisher=lambda book:publish_native_cashbook(self.root,self.monitor,book))
        self.client.accounts=[ACCOUNT];self.client.isConnected=lambda:True;self.calls=[]
        self.client.reqAccountUpdatesMulti=lambda *args:self.calls.append(('request',*args))
        self.client.cancelAccountUpdatesMulti=lambda request:self.calls.append(('cancel',request))
        self.client.cashbook_collector.monotonic=lambda:self.now
        self.monitor.begin([ACCOUNT]);self.monitor.state['api_protocol']={'connection':self.client.connection_generation}
        for end in ('orders','completed_orders','executions','positions'):self.monitor.end(end)
        self.target=self.root/'runtime/currency-book.latest.json'
    def request(self):
        self.client.poll_cashbook();return self.calls[-1][1]
    def feed(self,request):
        for key,value,currency in cash_fixtures.NativeCashCollectorTests().rows():
            self.client.accountUpdateMulti(request,ACCOUNT,'',key,value,currency)
    def complete(self):
        request=self.request();self.feed(request);self.now+=.1;self.client.accountUpdateMultiEnd(request);return request
    def test_optin_publishes_private_exact_native_file_without_order_permission(self):
        request=self.complete();book=json.loads(self.target.read_text())
        self.assertEqual(book['settlement_receipt']['request_id'],request)
        self.assertFalse(book['grants_trading_permission']);self.assertEqual(self.target.stat().st_mode&0o077,0)
        self.assertIn('sha256',self.monitor.state['currency_book_status'])
        self.assertEqual(self.monitor.coordinator.observations()['CURRENCY_BOOK']['state'],'HEALTHY')
    def test_server_event_time_is_not_replaced_by_callback_receipt_time(self):
        self.now+=.25;timestamp=int(self.now)
        self.client.currentTime(timestamp)
        evidence=self.monitor.state['native_server_clock']
        self.assertTrue(evidence['valid']);self.assertEqual(evidence['timestamp'],timestamp)
        self.assertEqual(evidence['received_at'],self.now)
        self.assertEqual(self.monitor.state['last_server_reply'],self.now)
    def test_invalid_server_time_never_refreshes_heartbeat(self):
        for timestamp in (True,None,float('nan'),float('inf'),int(self.now)-11,int(self.now)+11):
            before=self.monitor.state['last_server_reply'];self.now+=.1
            self.client.currentTime(timestamp)
            self.assertFalse(self.monitor.state['native_server_clock']['valid'])
            self.assertEqual(self.monitor.state['last_server_reply'],before)
    def test_old_client_server_callback_cannot_refresh_replacement_generation(self):
        before=self.monitor.state['last_server_reply']
        self.monitor.state['api_protocol']['connection']='replacement'
        self.now+=1;self.client.currentTime(int(self.now))
        self.assertEqual(self.monitor.state['last_server_reply'],before)
        self.assertNotIn('native_server_clock',self.monitor.state)
    def enable_pnl(self):
        client=PaperSafetyClient(self.monitor,['PFE'],native_pnl_observation=True)
        client.accounts=[ACCOUNT];client.isConnected=lambda:True
        client.reqPnL=lambda *args:self.calls.append(('pnl-request',*args))
        client.cancelPnL=lambda request:self.calls.append(('pnl-cancel',request))
        self.monitor.state['api_protocol']={'connection':client.connection_generation}
        client.pnl_collector.monotonic=lambda:self.now
        return client
    def test_optin_pnl_uses_existing_client_and_persists_exact_native_epoch(self):
        client=self.enable_pnl();client.poll_pnl();request=self.calls[-1][1]
        self.now+=.25;client.pnl(request,0,-12.5,2)
        receipt=self.monitor.state['native_pnl']
        self.assertEqual(receipt['broker_epoch'],self.monitor.state['epoch'])
        self.assertEqual(receipt['connection_generation'],client.connection_generation)
        self.assertEqual(receipt['daily'],0);self.assertFalse(receipt['grants_trading_permission'])
        self.assertEqual(self.calls[-1],('pnl-cancel',request))
        with closing(self.monitor.coordinator.connect()) as c:
            persisted=json.loads(c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()[0])
        self.assertEqual(persisted['native_pnl'],receipt)
    def test_new_reconciliation_rejects_old_pnl_frame_without_closing_actor(self):
        client=self.enable_pnl();client.poll_pnl();request=self.calls[-1][1]
        self.now+=.25;self.monitor.state['reconciled_at']=self.now
        client.pnl(request,1,2,3)
        self.assertNotIn('native_pnl',self.monitor.state)
        self.assertFalse(client.pnl_collector.closed)
        self.now+=30;client.currentTime(int(self.now));client.poll_pnl();client.pnl(self.calls[-1][1],1,2,3)
        self.assertIn('native_pnl',self.monitor.state)
    def test_pnl_epoch_change_at_same_clock_cannot_adopt_old_request(self):
        client=self.enable_pnl();client.poll_pnl();request=self.calls[-1][1]
        self.monitor.state['epoch']='new-reconciliation-at-same-clock'
        client.pnl(request,1,2,3)
        self.assertNotIn('native_pnl',self.monitor.state)
        self.assertEqual(self.calls[-1],('pnl-cancel',request))
    def test_pnl_storage_failure_latch_survives_replacement_sdk_client(self):
        client=self.enable_pnl();client.poll_pnl();request=self.calls[-1][1]
        with patch.object(self.monitor,'_publish',side_effect=OSError('fixture storage unavailable')):
            client.pnl(request,1,2,3)
        self.assertTrue(self.monitor.pnl_publication_state['blocked'])
        self.assertNotIn('native_pnl',self.monitor.state)
        replacement=PaperSafetyClient(self.monitor,['PFE'],native_pnl_observation=True)
        self.assertIsNone(replacement.pnl_collector)
        self.assertFalse(client.pnl_collector.poisoned)
    def test_cash_and_pnl_share_unique_request_allocator(self):
        self.client.native_pnl_observation=True;self.client._reset_pnl_collector()
        self.client.reqPnL=lambda *args:self.calls.append(('pnl-request',*args))
        self.client.cancelPnL=lambda request:self.calls.append(('pnl-cancel',request))
        cash=self.request();self.client.poll_pnl();pnl=self.calls[-1][1]
        self.assertNotEqual(cash,pnl)
        self.client.close_cashbook();self.client.close_pnl()
        self.assertIn(('cancel',cash),self.calls);self.assertIn(('pnl-cancel',pnl),self.calls)
    def test_default_client_has_no_cash_request_or_additional_worker(self):
        client=PaperSafetyClient(self.monitor,['PFE']);self.assertIsNone(client.cashbook_collector)
        client.poll_cashbook();client.close_cashbook()
        self.assertIsNone(client.pnl_collector);client.poll_pnl();client.close_pnl()
    def test_native_state_change_preserves_previous_file_and_never_publishes_partial(self):
        self.complete();before=self.target.read_bytes();self.now+=5
        request=self.request();self.feed(request);self.monitor.state['dirty']=True
        self.client.accountUpdateMultiEnd(request);self.assertEqual(self.target.read_bytes(),before)
        self.assertEqual(self.monitor.coordinator.observations()['CURRENCY_BOOK']['state'],'DEGRADED')
    def test_file_fsync_failure_preserves_previous_latest_and_private_failed_evidence(self):
        self.complete();before=self.target.read_bytes();self.now+=5
        request=self.request();self.feed(request)
        with patch('trading.native_cash_publication.os.fsync',side_effect=OSError('Fixture disk failure')):
            self.client.accountUpdateMultiEnd(request)
        self.assertEqual(self.target.read_bytes(),before)
        partials=list(self.target.parent.glob('.cashbook-*.tmp'));self.assertEqual(len(partials),1)
        self.assertEqual(partials[0].stat().st_mode&0o077,0)
        # Even a whole-process restart cannot multiply retained disk evidence.
        with self.assertRaises(OSError):
            publish_native_cashbook(self.root,self.monitor,json.loads(partials[0].read_text()))
        self.assertEqual(len(list(self.target.parent.glob('.cashbook-*.tmp'))),1)
        calls=len(self.calls)
        for _ in range(200):
            self.now+=5;self.client.poll_cashbook()
        self.assertEqual(len(self.calls),calls)
        self.assertFalse(self.client.cashbook_collector.poisoned)
        self.assertEqual(len(list(self.target.parent.glob('.cashbook-*.tmp'))),1)
        replacement=PaperSafetyClient(self.monitor,['PFE'],cashbook_publisher=lambda book:publish_native_cashbook(self.root,self.monitor,book))
        replacement.accounts=[ACCOUNT];replacement.isConnected=lambda:True
        replacement.reqAccountUpdatesMulti=lambda *args:self.fail('Fault latch lost across replacement client')
        replacement.poll_cashbook()
        self.assertTrue(replacement.cashbook_collector.publication_state['blocked'])
        self.assertEqual(self.monitor.coordinator.observations()['CURRENCY_BOOK']['state'],'DEGRADED')
    def test_generation_change_ignores_closed_previous_owner_callbacks(self):
        old=self.client.cashbook_collector;request=self.request();self.feed(request)
        self.client.isConnected=lambda:False
        with patch('ibapi.client.EClient.connect',return_value=None):self.client.connect('offline',4002,clientId=1)
        self.assertNotEqual(old.connection_generation,self.client.cashbook_collector.connection_generation)
        old.end(request);self.assertFalse(self.target.exists());self.assertTrue(old.closed)
        self.client.isConnected=lambda:True
        self.client.managedAccounts(ACCOUNT)  # New native session must confirm its account again.
        self.client.cashbook_collector.monotonic=lambda:self.now
        self.monitor.state['api_protocol']={'connection':self.client.connection_generation}
        next_request=self.request();self.assertNotEqual(next_request,request)
        self.feed(request);self.client.accountUpdateMultiEnd(request);self.assertFalse(self.target.exists())
        self.feed(next_request);self.client.accountUpdateMultiEnd(next_request);self.assertTrue(self.target.exists())
    def test_observation_storage_failure_is_visible_to_owner_loop_without_sdk_worker_death(self):
        request=self.request();self.feed(request)
        def fail(*args,**kwargs):raise OSError('Fixture health store unavailable')
        self.client.cashbook_collector.observe=fail
        self.client.accountUpdateMultiEnd(request)
        with self.assertRaises(RuntimeError):self.client.poll_cashbook()
        self.assertEqual(self.calls[-1],('cancel',request))
    def test_repeated_publication_closes_owned_file_and_sqlite_resources(self):
        fd_path=Path('/dev/fd');before=len(list(fd_path.iterdir()));threads=threading.active_count()
        for _ in range(30):self.complete();self.now+=5
        self.client.close_cashbook()
        self.assertLessEqual(len(list(fd_path.iterdir())),before+1)
        self.assertEqual(threading.active_count(),threads)
        self.assertEqual(list(self.target.parent.glob('.cashbook-*.tmp')),[])

    def test_later_reconciliation_epoch_prevents_old_cash_request_publication(self):
        request=self.request();self.feed(request);self.now+=.1
        self.monitor.state['reconciled_at']=self.now
        self.client.accountUpdateMultiEnd(request)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.monitor.coordinator.observations()['CURRENCY_BOOK']['state'],'DEGRADED')
        self.assertFalse(self.monitor.cashbook_publication_state.get('blocked',False))
        self.now=float(int(self.now)+6);self.complete();self.assertTrue(self.target.exists())

    def test_real_connect_layers_share_one_final_collector_generation(self):
        from ibapi.client import EClient
        self.client.native_pnl_observation=True;self.client._reset_pnl_collector()
        old_generation=self.client.connection_generation
        old_cash=self.client.cashbook_collector;old_pnl=self.client.pnl_collector
        with patch.object(EClient,'connect',return_value=None),patch.object(self.client,'isConnected',return_value=False):
            self.client.connect('unused',4002,99)
        generation=self.client.connection_generation
        self.assertNotEqual(generation,old_generation)
        self.assertEqual(self.client.cashbook_collector.connection_generation,generation)
        self.assertEqual(self.client.pnl_collector.connection_generation,generation)
        self.assertTrue(old_cash.closed);self.assertTrue(old_pnl.closed)
        with patch.object(self.client,'serverVersion',return_value=200),patch.object(self.client,'useProtoBuf',return_value=False):
            self.client.nextValidId(100)
        self.assertEqual(self.monitor.state['api_protocol']['connection'],generation)
        self.client.close_cashbook();self.client.close_pnl();self.client.disconnect()

class CashbookDependencyTests(unittest.TestCase):
    def test_dependency_is_optin_and_stale_cash_blocks_order_module_only_after_enabling(self):
        self.assertNotIn('CURRENCY_BOOK',dependency_registry({})['ORDER_SUBMISSION'])
        self.assertIn('CURRENCY_BOOK',dependency_registry({'CURRENCY_BOOK':{'enabled':True}})['ORDER_SUBMISSION'])
        now=datetime.fromisoformat('2026-11-09T21:00:00+00:00')
        observations={name:{'state':'HEALTHY','freshness':'FRESH','observed_at':now.isoformat()} for name in MODULE_DEPENDENCIES}
        observations['CURRENCY_BOOK'].update(enabled=True,observed_at='2026-11-09T20:59:49+00:00')
        view=resolve_modules(observations,now=now)
        self.assertNotEqual(view['CURRENCY_BOOK']['state'],'HEALTHY')
        self.assertIn('CURRENCY_BOOK',view['ORDER_SUBMISSION']['blocking_dependency'])
    def test_negative_currency_balances_are_facts_not_failed_adapters_or_trade_permission(self):
        now=datetime.now(timezone.utc)
        observations={name:{'state':'HEALTHY','freshness':'FRESH','observed_at':now.isoformat()} for name in MODULE_DEPENDENCIES}
        observations['CURRENCY_BOOK'].update(enabled=True,settled_usd='-69788.66',grants_trading_permission=False)
        view=resolve_modules(observations,now=now)
        self.assertEqual(view['CURRENCY_BOOK']['state'],'HEALTHY')
        self.assertFalse(view['CURRENCY_BOOK']['grants_trading_permission'])
