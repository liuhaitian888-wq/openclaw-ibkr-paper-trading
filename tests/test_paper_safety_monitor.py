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

    def upstream_incident(self):
        with closing(self.m.incidents.connect()) as c:
            return c.execute("SELECT generation,state FROM incidents WHERE incident_key='paper-safety:upstream'").fetchone()

    def test_upstream_recovery_requires_all_fresh_readback_and_reopens_next_occurrence(self):
        self.ready();self.m.error(1100)
        self.assertEqual(self.upstream_incident(),(1,'OPEN'))
        self.m.error(1102)
        for name in ('orders','completed_orders','executions'):self.m.end(name)
        self.assertEqual(self.upstream_incident(),(1,'OPEN'))
        self.m.end('positions')
        self.assertEqual(self.upstream_incident(),(1,'RESOLVED'))
        self.m.end('positions')
        with closing(self.m.incidents.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM notification_outbox WHERE incident_key='paper-safety:upstream' AND kind='RECOVERY'").fetchone()[0],1)
        self.m.error(1100)
        self.assertEqual(self.upstream_incident(),(2,'OPEN'))

    def test_end_callbacks_cannot_recover_disconnected_or_stale_upstream(self):
        self.ready();self.m.error(2110)
        for name in ('orders','completed_orders','executions','positions'):self.m.end(name)
        self.assertEqual(self.upstream_incident(),(1,'OPEN'))
        self.assertTrue(self.m.state['connected'])
        self.assertFalse(self.m.state['upstream_connected'])
        self.assertEqual(self.m.state['fault'],'IBKR_UPSTREAM_CONNECTION_LOST')
        self.m.error(1102);self.now+=11
        for name in ('orders','completed_orders','executions','positions'):self.m.end(name)
        self.assertEqual(self.upstream_incident(),(1,'OPEN'))

    def test_early_2110_is_durable_and_survives_managed_accounts_begin(self):
        client=PaperSafetyClient(self.m,['PFE'])
        client.error(-1,1794060496346,2110,'upstream broken','')
        self.m.begin([ACCOUNT],upstream_reported_lost=client.upstream_reported_lost)
        self.assertFalse(self.m.state['upstream_connected'])
        self.assertEqual(self.upstream_incident(),(1,'OPEN'))
        with closing(self.m.coordinator.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM paper_callback_events WHERE kind='error' AND json_extract(payload,'$.code')=2110").fetchone()[0],1)
        client.error(-1,1102,'restored','')
        self.assertFalse(client.upstream_reported_lost)

    def warm(self):
        self.now=1060
        self.m.bar('PFE',1000,1060)
        self.now=1120
        self.m.bar('PFE',1060,1120)
        self.m.quote('PFE',29,29.01,self.now,self.now,1)

    def notification_count(self):
        with closing(self.m.incidents.connect()) as c:
            return c.execute("SELECT count(*) FROM notification_outbox WHERE incident_key='paper-safety:protection:PFE'").fetchone()[0]

    def test_flat_exposure_closes_protection_only_after_complete_readback_and_reopens(self):
        self.ready(order=False)
        def incident():
            with closing(self.m.incidents.connect()) as c:
                return c.execute("SELECT generation,state FROM incidents WHERE incident_key='paper-safety:protection:PFE'").fetchone()
        self.assertEqual(incident(),(1,'OPEN'))
        self.m.start_reconciliation();self.m.position('PFE',0,con_id=11031,currency='USD',sec_type='STK')
        self.m.end('positions');self.assertEqual(incident(),(1,'OPEN'))
        for name in ('orders','completed_orders','executions'):self.m.end(name)
        self.assertEqual(incident(),(1,'RESOLVED'))
        count=self.notification_count();self.m._publish();self.assertEqual(self.notification_count(),count)
        self.m.start_reconciliation();self.m.position('PFE',2,con_id=11031,currency='USD',sec_type='STK')
        for name in ('positions','orders','completed_orders','executions'):self.m.end(name)
        self.assertEqual(incident(),(2,'OPEN'))

    def test_flat_position_with_active_order_does_not_clear_protection_incident(self):
        self.ready(order=False);self.m.start_reconciliation()
        self.m.position('PFE',0,con_id=11031,currency='USD',sec_type='STK')
        order=self.stop();order.update(side='BUY',order_type='LMT');self.m.order(order)
        for name in ('positions','orders','completed_orders','executions'):self.m.end(name)
        with closing(self.m.incidents.connect()) as c:
            self.assertEqual(c.execute("SELECT state FROM incidents WHERE incident_key='paper-safety:protection:PFE'").fetchone()[0],'OPEN')

    def test_reason_changes_do_not_create_repeated_pause_transitions(self):
        base=dict(scope='GLOBAL_NEW_ORDERS_PAUSED',affected_symbols=['PFE'],affected_strategies=['s'],reason='operator paused')
        self.m.state['pause_scopes']={}
        self.m.record_pause_transitions(dict(pauses=[base],decisions={}))
        for i in range(20):self.m.record_pause_transitions(dict(pauses=[dict(base,reason='sync '+str(i))],decisions={}))
        with closing(self.m.coordinator.connect()) as c:
            rows=[json.loads(r[0]) for r in c.execute("select payload from paper_callback_events where kind='pause_transition'")]
        selected=[r for r in rows if r.get('affected_strategies')==['s']]
        self.assertEqual(len(selected),1);self.assertEqual(self.m.state['pause_scopes']['pauses'][0]['reason'],'sync 19')

    def test_health_history_has_one_sample_per_minute_and_no_fake_backfill(self):
        for _ in range(10):self.m._publish()
        with closing(self.m.coordinator.connect()) as c:
            rows=c.execute('select observed,payload from paper_health_samples').fetchall()
        self.assertEqual(len(rows),1)
        first=json.loads(rows[0][1]);self.assertFalse(first['api_connected']);self.assertIn('PFE',first['market'])
        self.now+=120;self.m._publish()
        with closing(self.m.coordinator.connect()) as c:
            self.assertEqual(c.execute('select count(*) from paper_health_samples').fetchone()[0],2)

    def test_routine_snapshot_does_not_generate_protection_email_pairs(self):
        self.ready()
        count=self.notification_count()
        for _ in range(4):
            self.m.start_reconciliation()
            self.assertFalse(self.m.snapshot()['entries_ready'])
            self.assertEqual(self.m.protection()['PFE']['status'],'PROTECTION_UNKNOWN')
            self.m.position('PFE',2,con_id=11031,currency='USD',sec_type='STK')
            self.m.order(self.stop())
            for end in ('orders','completed_orders','executions','positions'):self.m.end(end)
        self.assertEqual(self.notification_count(),count)

    def test_routine_snapshot_timeout_and_disconnect_still_alert(self):
        self.ready(); count=self.notification_count()
        self.m.start_reconciliation();self.now+=31;self.m._publish()
        self.assertGreater(self.notification_count(),count)
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_data_loss_requires_resubscription_but_data_maintained_does_not(self):
        self.ready();self.m.error(1101)
        self.assertTrue(self.m.state['resubscribe_required'])
        self.assertFalse(self.m.snapshot()['entries_ready'])
        self.m.state['resubscribe_required']=False
        self.m.error(1102)
        self.assertFalse(self.m.state['resubscribe_required'])

    def test_1101_resubscription_is_consumed_once_by_owner(self):
        self.ready();client=PaperSafetyClient(self.m,['PFE'])
        client.retry_subscriptions=Mock()
        self.m.error(1101)
        self.assertTrue(client.recover_data_if_required())
        self.assertFalse(client.recover_data_if_required())
        client.retry_subscriptions.assert_called_once()
        self.m.error(1102)
        self.assertFalse(client.recover_data_if_required())
        self.assertEqual(client.retry_subscriptions.call_count,1)

    def test_delayed_frozen_and_delayed_frozen_never_pass(self):
        self.ready();self.warm()
        for kind in (2,3,4):
            self.m.quote('PFE',29,29.01,self.now,self.now,kind)
            self.assertFalse(self.m.snapshot()['data_ready'])

    def test_routine_refresh_disconnect_alerts_immediately(self):
        self.ready();count=self.notification_count()
        self.m.start_reconciliation();self.now+=1;self.m.error(1100)
        self.assertGreater(self.notification_count(),count)
        self.assertFalse(self.m.snapshot()['entries_ready'])

    def test_new_fill_during_refresh_is_not_silenced(self):
        self.ready();count=self.notification_count();self.m.start_reconciliation();self.now+=1
        self.m.execution(dict(exec_id='NEW',account=ACCOUNT,order_id=1,perm_id=101,
            order_ref='intent',symbol='PFE',side='BOT',shares=1,price=29,time='now'))
        self.assertGreater(self.notification_count(),count)

    def test_relevant_error_details_are_durable(self):
        self.ready();client=PaperSafetyClient(self.m,['PFE'])
        client.error(1,162,'Historical data service: competing session')
        with closing(self.m.coordinator.connect()) as c:
            row=c.execute("SELECT payload FROM paper_callback_events WHERE kind='error'").fetchone()
        self.assertEqual(json.loads(row[0])['code'],162)

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
        for _ in range(3):
            self.now=self.m.state['retry_at']
            self.assertTrue(self.m.retry_due())
            self.assertLessEqual(self.m.state['retry_at']-self.now,300)
        self.now+=10000
        self.assertFalse(self.m.retry_due())
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

    def test_completed_callbacks_with_zero_local_id_keep_distinct_permanent_orders(self):
        client=PaperSafetyClient(self.m,['PFE']);self.m.begin([ACCOUNT])
        contract=NS(symbol='NVDA',conId=4815747,currency='USD',secType='STK')
        for perm,side in ((756941085,'BUY'),(756941086,'SELL')):
            order=NS(orderId=0,permId=perm,account=ACCOUNT,action=side,orderType='LMT',totalQuantity=0,transmit=True,clientId=0)
            client.completedOrder(contract,order,NS(status='Filled'))
        self.assertEqual(len(self.m.state['orders']),2)
        self.assertEqual({o['perm_id'] for o in self.m.state['orders'].values()},{756941085,756941086})
        self.assertNotIn(0,client.broker_orders)
        self.assertTrue(self.m.state['connected'])

    def test_completed_permanent_identity_conflict_is_still_rejected(self):
        base=dict(order_id=0,perm_id=111,account=ACCOUNT,client_id=0,con_id=4815747,symbol='NVDA',side='BUY',completed=True,status='Filled')
        self.m.order(base)
        with self.assertRaises(ValueError):self.m.order(dict(base,symbol='PFE'))
        self.assertFalse(self.m.state['connected'])

    def test_completed_order_without_permanent_id_cannot_be_merged(self):
        with self.assertRaises(ValueError):self.m.order(dict(order_id=0,perm_id=0,account=ACCOUNT,completed=True))

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

    def test_read_only_completed_request_rejection_never_marks_reconciled(self):
        client=PaperSafetyClient(self.m,['PFE'])
        self.m.begin([ACCOUNT])
        client.error(-1,1234567890123,321,'The API interface is currently in Read-Only mode.','')
        self.assertTrue(client.read_only_completed_orders_blocked)
        self.assertTrue(self.m.state['connected'])
        self.assertFalse(self.m.snapshot()['reconciliation_complete'])

class SymbolIsolationAdapterTests(unittest.TestCase):
 def test_targeted_conflict_keeps_healthy_peer_and_bar_subscriptions_scoped(self):
  from tempfile import TemporaryDirectory
  from pathlib import Path
  from unittest.mock import Mock
  from trading.paper_safety_client import PaperSafetyClient
  with TemporaryDirectory() as tmp:
   r=Path(tmp);m=PaperSafetyMonitor(r/'audit.db',r/'recovery.db',symbols=['GOOD','BAD'],required_bars=1,clock=lambda:1000)
   m.state['quotes']={'GOOD':dict(bid=10,ask=11,bid_at=1000,ask_at=1000,data_type=1),'BAD':{}}
   m.state['bars']={'GOOD':[960],'BAD':[960]}
   m.error(10197,symbol='BAD')
   self.assertIn('GOOD',m.state['quotes']);self.assertEqual(m.state['bars']['GOOD'],[960])
   self.assertNotIn('BAD',m.state['quotes'])
   client=PaperSafetyClient(m,['GOOD','BAD'])
   client.placeOrder=Mock(side_effect=AssertionError('Order mutation forbidden'));client.cancelOrder=Mock(side_effect=AssertionError('Protection cancellation forbidden'))
   m.state['orders']={'existing-stop':{'symbol':'GOOD','perm_id':911411084,'status':'PreSubmitted','remaining':8}}
   import copy,os
   before=copy.deepcopy(m.state['orders'])
   controls={k:os.environ.get(k) for k in ('ALLOW_PAPER_TRANSMIT','TRADING_KILL_SWITCH')}
   client.reqMarketDataType=Mock();client.cancelMktData=Mock();client.reqMktData=Mock();client.cancelRealTimeBars=Mock();client.reqRealTimeBars=Mock()
   client.retry_symbol_subscriptions(['BAD'],bars_only=True)
   client.cancelMktData.assert_not_called();client.reqMktData.assert_not_called()
   client.reqRealTimeBars.assert_called_once();self.assertEqual(client.reqRealTimeBars.call_args.args[0],47001)
   client.placeOrder.assert_not_called();client.cancelOrder.assert_not_called()
   self.assertEqual(m.state['orders'],before)
   self.assertEqual(controls,{k:os.environ.get(k) for k in controls})
