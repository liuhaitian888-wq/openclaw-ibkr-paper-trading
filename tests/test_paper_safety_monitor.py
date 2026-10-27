from contextlib import closing
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from reporting.health import resolve_modules
from reporting.incident_mail import message_for, send_one
from trading.paper_safety_monitor import PaperSafetyMonitor, ACCOUNT
from trading.paper_safety_client import PaperSafetyClient


class PaperSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=1000.0
        self.m=self.make()

    def make(self):
        return PaperSafetyMonitor(self.root/'audit.db',self.root/'recovery.db',symbols=['PFE'],required_bars=2,clock=lambda:self.now)

    def stop(self, **changes):
        return dict(order_id=2,perm_id=102,account=ACCOUNT,symbol='PFE',side='SELL',order_type='STP',
                    status='Submitted',quantity=2,remaining=2,transmit=True,parent_id=0,
                    con_id=11031,currency='USD',sec_type='STK',**changes)

    def ready(self, qty=2, order=None):
        self.m.begin([ACCOUNT])
        self.m.position('PFE',qty,con_id=11031,currency='USD',sec_type='STK')
        if order is not False:
            self.m.order(order or self.stop())
        for name in ('orders','completed_orders','executions','positions'):
            self.m.end(name)

    def warm(self):
        self.now=1060
        self.m.bar('PFE',1000,1060)
        self.now=1120
        self.m.bar('PFE',1060,1120)
        self.m.quote('PFE',29,29.01,self.now,self.now,1)

    def test_native_accepted_stop_and_fresh_complete_bars(self):
        self.ready()
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTED')
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.warm()
        self.assertTrue(self.m.snapshot()['entries_ready'])
        self.now+=6
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_partial_fill_and_duplicate_execid_persist_once(self):
        self.ready()
        e=dict(exec_id='E1',account=ACCOUNT,order_id=1,perm_id=101,order_ref='intent',symbol='PFE',side='BOT',shares=1,price=29,time='now')
        self.m.execution(e)
        self.m.execution(e)
        with closing(sqlite3.connect(self.root/'audit.db')) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM executions').fetchone()[0],1)
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')
        self.m.start_reconciliation()
        self.m.position('PFE',3,con_id=11031,currency='USD',sec_type='STK')
        self.m.order(self.stop())
        for end in ('positions','orders','completed_orders','executions'):
            self.m.end(end)
        self.assertEqual(self.m.protection()['PFE']['status'],'PARTIALLY_PROTECTED')
        self.assertFalse(self.m.snapshot()['entries_ready'])
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            self.m.execution({**e,'shares':2})
        self.assertFalse(self.m.state['connected'])

    def test_untransmitted_cancelled_rejected_missing_stop(self):
        for patch in ({'transmit':False},{'status':'Cancelled'},{'status':'Inactive'},{'perm_id':0}):
            self.m=self.make()
            self.ready(order={**self.stop(),**patch})
            self.assertEqual(self.m.protection()['PFE']['status'],'UNPROTECTED')
            self.assertFalse(self.m.snapshot()['entries_ready'])
        self.m=self.make()
        self.ready(order=False)
        self.assertEqual(self.m.protection()['PFE']['status'],'UNPROTECTED')

    def test_attached_partial_parent_and_oca_are_not_assumed_active(self):
        self.ready(order={**self.stop(),'parent_id':1})
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')
        self.m.order(dict(order_id=1,account=ACCOUNT,symbol='PFE',status='Filled',filled=2,side='BUY',con_id=11031))
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.m.start_reconciliation()
        self.m.position('PFE',2,con_id=11031,currency='USD',sec_type='STK')
        self.m.order({**self.stop(),'parent_id':1})
        self.m.order(dict(order_id=1,account=ACCOUNT,symbol='PFE',status='Filled',filled=2,side='BUY',con_id=11031))
        for end in ('positions','orders','completed_orders','executions'):
            self.m.end(end)
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTED')
        self.m.order({**self.stop(),'oca_group':'overlapping'})
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')

    def test_restart_and_disconnect_never_reuse_health(self):
        self.ready()
        self.warm()
        self.m=self.make()
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')
        self.m.error(1100)
        self.assertFalse(self.m.snapshot()['reconciliation_complete'])
        self.m.begin([ACCOUNT])
        self.m.position('PFE',2,con_id=11031,currency='USD',sec_type='STK')
        self.m.end('orders')
        self.m.end('positions')
        self.assertFalse(self.m.snapshot()['reconciliation_complete'])

    def test_10197_monitoring_survives_and_backoff_is_bounded(self):
        self.ready()
        self.warm()
        self.m.error(10197)
        self.assertTrue(self.m.state['connected'])
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTED')
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.assertFalse(self.m.retry_due())
        self.now+=30
        self.assertTrue(self.m.retry_due())
        self.assertEqual(self.m.state['retry_at']-self.now,60)
        for _ in range(6):
            self.now=self.m.state['retry_at']
            self.assertTrue(self.m.retry_due())
            self.assertLessEqual(self.m.state['retry_at']-self.now,300)
        self.assertTrue(self.m.state['connected'])

    def test_stale_delayed_crossed_and_incomplete_bars_cannot_recover(self):
        self.ready()
        self.m.error(10197)
        self.warm()
        for bid,ask,kind in ((30,29,1),(29,30,3),(0,30,1)):
            self.m.quote('PFE',bid,ask,self.now,self.now,kind)
            self.assertFalse(self.m.snapshot()['entries_ready'])
        self.m.state['bars']={}
        self.m.bar('PFE',self.now,self.now+60)
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_incident_dedup_recovery_and_priority_mail(self):
        self.ready(order=False)
        for _ in range(5):
            self.now+=1
            self.m._publish()
        with closing(self.m.incidents.connect()) as c:
            rows=c.execute("SELECT incident_key,generation,kind,payload FROM notification_outbox WHERE incident_key='paper-safety:protection:PFE'").fetchall()
        self.assertEqual(len(rows),2)  # UNKNOWN -> confirmed missing stop alerts once each.
        key,generation,kind,payload=rows[-1]
        mail=message_for(dict(incident_key=key,generation=generation,kind=kind,payload=json.loads(payload)),'sender@example.invalid','TEST')
        self.assertEqual(mail['Importance'],'high')
        self.assertIn('UNPROTECTED',mail.get_content())
        self.assertIn('Incident ID',mail.get_content())
        self.m.order(self.stop())
        with closing(self.m.incidents.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE incident_key=? AND kind='RECOVERY'",(key,)).fetchone()[0],1)

    def test_shared_graph_expires_safety_heartbeat_after_five_seconds(self):
        self.ready()
        observations=self.m.coordinator.observations()
        self.now+=6
        from datetime import datetime,timezone
        modules=resolve_modules(observations,now=datetime.fromtimestamp(self.now,timezone.utc))
        self.assertNotEqual(modules['PROTECTION']['state'],'HEALTHY')
        self.assertNotEqual(modules['PAPER_SESSION']['state'],'HEALTHY')

    def test_actual_callback_adapter_exec_partial_and_error(self):
        client=PaperSafetyClient(self.m,['PFE'])
        self.m.begin([ACCOUNT])
        contract=NS(symbol='PFE',conId=11031,currency='USD',secType='STK')
        order=NS(orderId=2,permId=102,account=ACCOUNT,action='SELL',orderType='STP',totalQuantity=2,transmit=True)
        client.openOrder(2,contract,order,NS(status='Submitted'))
        self.assertIsNone(self.m.state['orders']['2'].get('remaining'))
        client.orderStatus(2,'Submitted',Decimal(0),Decimal(2),0,102,0,0,77,'',0)
        client.position(ACCOUNT,contract,Decimal(2),29)
        client.openOrderEnd();client.completedOrdersEnd();client.positionEnd();client.execDetailsEnd(48000)
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTED')
        client.error(-1,1234567890123,10197,'conflict','')
        self.assertTrue(self.m.state['connected'])
        client.placeOrder=Mock(side_effect=AssertionError('No broker mutations'))
        client.cancelOrder=Mock(side_effect=AssertionError('No broker mutations'))
        client.connectionClosed()
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_complete_kline_requires_all_twelve_real_bars(self):
        client=PaperSafetyClient(self.m,['PFE'])
        self.now=1200
        self.m.state['reset_at']=1020
        for t in range(1020,1075,5):
            client.realtimeBar(47000,t,1,1,1,1,0,0,0)
        self.assertEqual(self.m.state['bars'],{})
        client.realtimeBar(47000,1075,1,1,1,1,0,0,0)
        self.assertEqual(self.m.state['bars']['PFE'],[1080])

    def test_read_only_resync_requests_all_broker_truth(self):
        client=PaperSafetyClient(self.m,['PFE'])
        for method in ('reqAllOpenOrders','reqCompletedOrders','reqExecutions','reqPositions'):
            setattr(client,method,Mock())
        client.reconcile()
        client.reqAllOpenOrders.assert_called_once()
        client.reqCompletedOrders.assert_called_once_with(False)
        client.reqExecutions.assert_called_once()
        client.reqPositions.assert_called_once()
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_collision_recovery_requires_a_new_broker_snapshot(self):
        self.ready()
        self.m.error(10197)
        self.warm()
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.ready()
        self.assertTrue(self.m.snapshot()['entries_ready'])
        self.assertIsNone(self.m.state['collision_since'])

    def test_wrong_contract_stop_never_covers_position(self):
        self.ready(order={**self.stop(),'con_id':99999})
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')

    def test_fill_arriving_during_snapshot_requires_another_readback(self):
        self.m.begin([ACCOUNT])
        self.m.position('PFE',2,con_id=11031,currency='USD',sec_type='STK')
        self.m.execution(dict(exec_id='new',account=ACCOUNT,order_id=1,perm_id=101,order_ref='intent',symbol='PFE',side='BOT',shares=1,price=29,time='now'))
        for end in ('positions','orders','completed_orders','executions'):
            self.m.end(end)
        self.assertFalse(self.m.snapshot()['reconciliation_complete'])

    def test_safety_incident_uses_existing_smtp_transport_once(self):
        self.ready(order=False)
        smtp=Mock()
        smtp.__enter__=Mock(return_value=smtp)
        smtp.__exit__=Mock(return_value=False)
        smtp.send_message.return_value={}
        factory=Mock(return_value=smtp)
        cfg=dict(host='smtp.example.invalid',sender='sender@example.invalid',username='test-user',relay_password='offline-placeholder')
        self.assertEqual(send_one(self.m.incidents,self.m.coordinator,cfg,smtp_factory=factory),'SMTP_ACCEPTED')
        sent=smtp.send_message.call_args.args[0]
        self.assertEqual(sent['Importance'],'high')
        self.assertIn('PFE',sent.get_content())
        self.assertIn('Incident ID',sent.get_content())
        self.assertFalse(self.m.incidents.uncertain_notifications())

    def test_silent_socket_cannot_keep_protection_healthy(self):
        self.ready()
        self.now+=11
        self.m._publish()
        self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_persisted_execution_conflict_survives_missing_state_commit(self):
        execution=dict(exec_id='persisted',account=ACCOUNT,order_id=1,perm_id=101,order_ref='intent',symbol='PFE',side='BOT',shares=1,price=29,time='now')
        self.m.execution(execution)
        # Simulate crash between audit commit and recovery snapshot commit.
        self.m.state['executions']={}
        with self.assertRaisesRegex(ValueError,'EXECUTION_CONFLICT'):
            self.m.execution({**execution,'price':30})
        with closing(sqlite3.connect(self.root/'audit.db')) as c:
            self.assertEqual(c.execute('SELECT price FROM executions WHERE exec_id=?',('persisted',)).fetchone()[0],29)

    def test_callback_history_deduplicates_identical_order_events(self):
        self.ready()
        self.m.order(self.stop())
        self.m.order(self.stop())
        with closing(self.m.coordinator.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM paper_callback_events WHERE kind='order'").fetchone()[0],1)
