from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from reporting.health import dependency_registry, callback_owned_modules
from trading.sqlite_event_store import SQLiteEventStore
from trading.native_health_bridge import NativeOwnerHealthBridge, disable_native_health_owner
from tests import test_native_cash_owner as owner_fixtures


class NativeHealthBridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=owner_fixtures.NativeCashOwnerTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.monitor=self.fixture.monitor;self.co=self.monitor.coordinator
        SQLiteEventStore(self.monitor.audit._path)
        self.refresh_book()
        self.bridge=NativeOwnerHealthBridge(self.fixture.root,self.monitor,monotonic=lambda:self.fixture.now)
        self.addCleanup(self.bridge.close)
    def refresh_book(self):
        f=self.fixture;f.client.currentTime(int(f.now))
        request=f.request();f.feed(request)
        for key,value in (('NetLiquidation','1014994.80'),('BuyingPower','123456')):
            f.client.accountUpdateMulti(request,'DUQ503649','',key,value,'EUR')
        f.client.accountUpdateMultiEnd(request)
        stamp=datetime.fromtimestamp(f.now,timezone.utc).isoformat()
        self.monitor.state['native_pnl']=dict(account='DUQ503649',source='NATIVE_ACCOUNT_PNL',
            connection_generation=f.client.connection_generation,broker_epoch=self.monitor.state['epoch'],
            admission_generation=self.monitor.state['epoch'],started_at=stamp,observed_at=stamp,
            daily=0,unrealized=-12.5,realized=2,grants_trading_permission=False)
    def test_real_callback_and_local_commit_evidence_unblocks_data_not_financial_permission(self):
        self.co.observe('NETWORK','FAILED',reason='Unverified public egress')
        self.bridge.poll()
        for name in ('NATIVE_BROKER_SESSION','IBKR_CONNECTION','ACCOUNT','EXECUTIONS','DATABASE','AUDIT','LOCAL_STATE'):
            self.assertEqual(self.co.observations()[name]['state'],'HEALTHY',name)
        self.assertEqual(self.co.snapshot()['ACCOUNT']['state'],'HEALTHY')
        self.assertEqual(self.co.observations()['NETWORK']['state'],'FAILED')
        self.assertNotEqual(self.co.snapshot()['STRATEGY']['state'],'HEALTHY')
        self.assertNotEqual(self.co.snapshot()['RISK']['state'],'HEALTHY')
        self.assertFalse(self.co.observations()['ACCOUNT']['grants_trading_permission'])
        self.fixture.now+=5;self.refresh_book();self.bridge.poll()
        self.assertEqual(self.co.snapshot()['CURRENCY_BOOK']['state'],'HEALTHY')
    def test_delivery_unknown_does_not_hide_actual_account_facts_or_get_replayed(self):
        self.co.begin_operation('notice:lost','delivery',{});self.co.finish_operation('notice:lost','UNKNOWN')
        self.bridge.poll()
        self.assertEqual(self.co.observations()['EXECUTIONS']['state'],'HEALTHY')
        self.assertEqual(self.co.uncertainties(),[('notice:lost','delivery','UNKNOWN')])
    def test_order_unknown_holds_broker_modules_and_preserves_operation(self):
        self.co.begin_operation('order:lost','order',{});self.co.finish_operation('order:lost','UNKNOWN')
        self.bridge.poll()
        for name in ('ORDERS','EXECUTIONS'):self.assertEqual(self.co.observations()[name]['state'],'DEGRADED')
        self.assertEqual(self.co.uncertainties(),[('order:lost','order','UNKNOWN')])
    def test_persisted_pnl_cannot_bypass_its_owner_failure_latch(self):
        self.monitor.pnl_publication_state['blocked']=True
        self.bridge.poll()
        self.assertNotEqual(self.co.observations()['ACCOUNT']['state'],'HEALTHY')
    def test_local_audit_failure_never_creates_missing_database(self):
        path=self.monitor.audit._path;path.unlink()
        self.bridge.poll()
        self.assertFalse(path.exists())
        self.assertEqual(self.co.observations()['DATABASE']['state'],'FAILED')
        self.assertEqual(self.co.observations()['AUDIT']['state'],'FAILED')
    def test_journal_failure_does_not_raise_into_sdk_owner_loop(self):
        with patch.object(self.co,'uncertainties',side_effect=OSError('fixture journal unavailable')):
            self.bridge.poll()
        self.assertEqual(self.co.observations()['ORDERS']['state'],'DEGRADED')
    def test_local_probes_are_bounded_per_minute_and_close_resources(self):
        before=len(list(Path('/dev/fd').iterdir()));threads=threading.active_count()
        self.bridge.poll()
        for _ in range(59):self.fixture.now+=1;self.bridge.poll()
        with closing(self.monitor.audit._connect()) as c:
            count=c.execute("SELECT count(*) FROM event_store WHERE source_module='dependency_adapter' AND event_type='WRITE_PROBE'").fetchone()[0]
        self.assertEqual(count,1)
        self.fixture.now+=1;self.bridge.poll()
        with closing(self.monitor.audit._connect()) as c:
            count=c.execute("SELECT count(*) FROM event_store WHERE source_module='dependency_adapter' AND event_type='WRITE_PROBE'").fetchone()[0]
        self.assertEqual(count,2)
        self.assertLessEqual(len(list(Path('/dev/fd').iterdir())),before+1)
        self.assertEqual(threading.active_count(),threads)
    def test_disconnect_invalidates_dependents_without_reconnect_or_side_effect(self):
        self.bridge.poll();self.monitor.state['connected']=False;self.fixture.now+=1
        self.bridge.poll()
        self.assertEqual(self.co.observations()['NATIVE_BROKER_SESSION']['state'],'DEGRADED')
        self.assertNotEqual(self.co.snapshot()['ACCOUNT']['state'],'HEALTHY')
    def test_generic_recovery_cannot_promote_or_create_another_native_owner(self):
        called=[]
        self.co.adapters={name:lambda step:called.append(step) or True for name in callback_owned_modules(self.co.observations())}
        self.co.tick();self.assertEqual(called,[])
        self.assertNotEqual(self.co.observations()['ACCOUNT']['state'],'HEALTHY')
    def test_unimplemented_market_and_risk_recovery_cannot_allocate_another_broker_client(self):
        self.bridge.poll();called=[]
        self.co.adapters={name:lambda step:called.append(step) or True for name in ('MARKET_DATA','RISK')}
        self.co.tick();self.assertEqual(called,[])
        for module in ('MARKET_DATA','RISK'):
            self.assertNotEqual(self.co.observations().get(module,{}).get('state'),'HEALTHY')
    def test_direct_generic_adapter_is_denied_before_any_broker_transport(self):
        from unittest.mock import Mock
        from reporting.recovery import wire_live_adapters
        (self.fixture.root/'production.json').write_text(json.dumps({'account':'DUQ503649','market_symbols':['PFE']}))
        probe=Mock(side_effect=AssertionError('Generic broker client must not be created'))
        adapters=wire_live_adapters(self.co,self.fixture.root,self.fixture.root,broker_probe=probe)
        for module in ('ACCOUNT','MARKET_DATA','RISK'):
            self.assertFalse(adapters[module]('connect'))
            self.assertIn('reserves broker transport',adapters[module].observation['reason'])
        probe.assert_not_called()
    def test_optout_invalidates_old_owner_and_restores_legacy_network_dependency(self):
        self.bridge.poll()
        self.assertEqual(dependency_registry(self.co.observations())['IBKR_CONNECTION'],('NATIVE_BROKER_SESSION',))
        disable_native_health_owner(self.co)
        self.assertEqual(dependency_registry(self.co.observations())['IBKR_CONNECTION'],('NETWORK',))
        self.assertNotEqual(self.co.observations()['ACCOUNT']['state'],'HEALTHY')
    def test_repeated_parent_loss_retains_parent_occurrences_without_duplicate_child_phase(self):
        self.co.observe('ACCOUNT','DEGRADED',reason='fixture source unavailable')
        def events(module):
            with closing(self.co.connect()) as c:
                return c.execute("SELECT count(*) FROM module_events WHERE json_extract(payload,'$.module')=?",(module,)).fetchone()[0]
        before=events('CURRENCY_BOOK');parents=events('ACCOUNT')
        for _ in range(20):
            self.co.observe('ACCOUNT','HEALTHY',freshness='FRESH',reason='fixture source ready')
            self.co.observe('ACCOUNT','DEGRADED',reason='fixture source unavailable')
        self.assertEqual(events('CURRENCY_BOOK'),before)
        self.assertEqual(events('ACCOUNT'),parents+40)
        self.co.observe('CURRENCY_BOOK','HEALTHY',freshness='FRESH',reason='fixture fresh read')
        self.co.observe('ACCOUNT','HEALTHY',freshness='FRESH',reason='fixture source ready')
        self.co.observe('ACCOUNT','DEGRADED',reason='fixture source unavailable')
        self.assertEqual(events('CURRENCY_BOOK'),before+2)
    def test_close_keeps_owner_route_reserved_and_blocks_old_callback_facts(self):
        self.bridge.poll();self.bridge.close()
        self.assertTrue(self.co.observations()['NATIVE_BROKER_SESSION']['enabled'])
        self.assertEqual(self.co.observations()['NATIVE_BROKER_SESSION']['state'],'PAUSED')
        self.assertNotEqual(self.co.snapshot()['ACCOUNT']['state'],'HEALTHY')
