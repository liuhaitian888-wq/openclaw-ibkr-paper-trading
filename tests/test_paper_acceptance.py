from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from trading.audit import AuditLog
from trading.paper_acceptance import Journal,check_order,validate_scope,owned_order,ACCOUNT,CLIENT_ID,check_session


class PaperAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'audit.sqlite3';AuditLog(self.path)
        self.j=Journal(self.path,'pa-20261106-nvda-v1')
    def facts(self):
        return dict(stage='fill',bid=179.,ask=179.1,bid_at=100,ask_at=100,data_type=1,
                    limit=179.1,min_tick=.01,position=0,baseline=0,usd_cash=1000,
                    available_funds=1000,orders=[],now=100)
    def test_real_quotes_and_cash_and_owned_one_share(self):
        d=self.facts();r=check_order(**d);self.assertEqual(r['quantity'],1);self.assertEqual(r['side'],'BUY')
        d.update(stage='close',position=1);self.assertEqual(check_order(**d)['side'],'SELL')
    def test_missing_stale_frozen_crossed_nan_and_limit_block(self):
        for key,value in (('bid_at',96),('ask_at',101),('data_type',3),('bid',180),('ask',float('nan')),('limit',201),('position',1),('baseline',1),('min_tick',.04)):
            d=self.facts();d[key]=value
            with self.subTest(key=key),self.assertRaises(PermissionError):check_order(**d)
    def test_manual_orders_count_for_cash_and_unbounded_exposure_blocks(self):
        d=self.facts();d['orders']=[dict(account=ACCOUNT,symbol='OTHER',side='BUY',currency='USD',order_type='LMT',limit=100,remaining=9)]
        with self.assertRaises(PermissionError):check_order(**d)
        d['orders'][0]['order_type']='MKT'
        with self.assertRaises(PermissionError):check_order(**d)
        d['orders']=[dict(account=ACCOUNT,symbol='PFE',side='SELL',remaining=8,held_position=8)]
        check_order(**d)
        d['orders'][0]['held_position']=7
        with self.assertRaises(PermissionError):check_order(**d)
    def test_pending_unknown_and_duplicate_never_replay_across_restart(self):
        ref=self.j.reserve('cancel',dict(order_id=2))
        restarted=Journal(self.path,self.j.scope_id)
        with self.assertRaises(PermissionError):restarted.reserve('cancel',{})
        with self.assertRaises(PermissionError):restarted.reserve('fill',{})
        self.j.finish(ref,'UNKNOWN',dict(reason='lost ack'))
        with self.assertRaises(PermissionError):restarted.reserve('cancel',{})
    def test_serial_stages_preserve_audit_and_native_evidence(self):
        ref=self.j.reserve('cancel',dict(order_id=2));self.j.event(ref,'ORDER_STATUS',dict(status='Submitted'))
        self.j.finish(ref,'CANCELLED',dict(perm_id=99))
        ref2=self.j.reserve('fill',dict(order_id=3));self.j.finish(ref2,'FILLED',dict(status='FILLED',exec_ids=['real-1']))
        self.assertEqual(self.j.read('fill')['exec_ids'],['real-1'])
        ref3=self.j.reserve('close',dict(order_id=4));self.j.finish(ref3,'FILLED',{})
        with closing(self.j.connect()) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM order_requests').fetchone()[0],3)
        with self.assertRaises(PermissionError):self.j.reserve('fill',{})
    def test_cannot_cancel_existing_pfe_or_other_client_or_ref(self):
        o=NS(account=ACCOUNT,clientId=CLIENT_ID,orderRef='test',orderId=4,action='BUY',totalQuantity=1)
        c=NS(symbol='NVDA',currency='USD');self.assertTrue(owned_order(o,c,'test',4))
        for key,value in (('clientId',3130),('orderRef','protect-pfe'),('account','U123')):
            old=getattr(o,key);setattr(o,key,value);self.assertFalse(owned_order(o,c,'test',4));setattr(o,key,old)
        c.symbol='PFE';self.assertFalse(owned_order(o,c,'test',4))
    def test_scope_identity_expiry_and_global_gate_tamper(self):
        (self.root/'production.json').write_text('{"ready":false}')
        actual=dict(commit='abc',branch='codex/paper',code_root='/opt/openclaw/app',state_root=str(self.root))
        now=datetime.now(timezone.utc)
        s=dict(actual,approved=True,environment='PAPER',account=ACCOUNT,symbol='NVDA',client_id=CLIENT_ID,quantity=1,max_limit=200,max_submissions=3,
               maintenance_test_authorized=True,grants_strategy_permission=False,id=self.j.scope_id,expires_at=(now+timedelta(hours=1)).isoformat(),
               preserved_files={'production.json':hashlib.sha256((self.root/'production.json').read_bytes()).hexdigest(),'PAUSED':'ABSENT','runtime/MAINTENANCE':'ABSENT'})
        validate_scope(s,actual,self.root,now)
        with self.assertRaises(PermissionError):validate_scope(s,{**actual,'commit':'other'},self.root,now)
        with self.assertRaises(PermissionError):validate_scope(s,actual,self.root,now+timedelta(hours=2))
        (self.root/'PAUSED').write_text('changed')
        with self.assertRaises(PermissionError):validate_scope(s,actual,self.root,now)
    def test_after_hours_uses_actual_contract_schedule_and_eastern_date(self):
        now=datetime.fromisoformat('2026-11-06T00:20:00+01:00')
        self.assertTrue(check_session('20261105:0400-20261105:2000','US/Eastern',now))
        with self.assertRaises(PermissionError):check_session('20261105:CLOSED','US/Eastern',now)
        with self.assertRaises(PermissionError):check_session('20261105:0930-20261105:1600','US/Eastern',now)

    def test_real_runner_cancel_path_uses_transport_once_and_closes_owned_client(self):
        import asyncio,contextlib,io,sys
        from unittest.mock import patch
        import ops.cloud.paper_acceptance as runner
        now=datetime.now(timezone.utc)
        d=now.strftime('%Y%m%d')
        actual=dict(commit='abc',branch='codex/paper',code_root='/opt/openclaw/app',state_root=str(self.root))
        (self.root/'runtime').mkdir();(self.root/'production.json').write_text('{"ready":false}')
        # Canonical audit filename is explicit, never a production path in tests.
        AuditLog(self.root/'trading_audit.sqlite3')
        scope=dict(actual,approved=True,environment='PAPER',account=ACCOUNT,symbol='NVDA',client_id=CLIENT_ID,quantity=1,max_limit=200,max_submissions=3,
               maintenance_test_authorized=True,grants_strategy_permission=False,id=self.j.scope_id,expires_at=(now+timedelta(hours=1)).isoformat(),
               preserved_files={'production.json':hashlib.sha256((self.root/'production.json').read_bytes()).hexdigest(),'PAUSED':'ABSENT','runtime/MAINTENANCE':'ABSENT'})
        (self.root/'runtime/paper-acceptance-scope.json').write_text(json.dumps(scope))
        class Event:
            def __init__(self):self.handlers=[]
            def __iadd__(self,h):self.handlers.append(h);return self
            def __isub__(self,h):self.handlers.remove(h);return self
            def emit(self,*a):
                for h in self.handlers:h(*a)
        class Fake:
            def __init__(self):
                self.errorEvent=Event();self.pendingTickersEvent=Event();self.orderStatusEvent=Event();self.execDetailsEvent=Event()
                self.client=NS(getReqId=lambda:3,reqAccountSummary=lambda *args:None,cancelAccountSummary=lambda req:None)
                def start_req(req):
                    f=asyncio.get_running_loop().create_future();f.set_result(None);return f
                self.wrapper=NS(startReq=start_req,acctSummary={0:NS(account=ACCOUNT,tag='CashBalance',currency='USD',value='1000'),1:NS(account=ACCOUNT,tag='AvailableFunds',currency='USD',value='1000')})
                self.sent=0;self.cancelled=0;self.closed=False
            def isConnected(self):return True
            async def connectAsync(self,*a,**k):pass
            def managedAccounts(self):return [ACCOUNT]
            async def qualifyContractsAsync(self,*a):return [NS(conId=1,symbol='NVDA',currency='USD')]
            async def reqContractDetailsAsync(self,c):
                tomorrow=(now+timedelta(days=1)).strftime('%Y%m%d')
                return [NS(minTick=.01,tradingHours=f'{d}:0000-{tomorrow}:0000',timeZoneId='UTC')]
            async def reqPositionsAsync(self):return []
            async def reqAllOpenOrdersAsync(self):return []
            async def accountSummaryAsync(self,a):return [NS(account=a,tag='CashBalance',currency='USD',value='1000'),NS(account=a,tag='AvailableFunds',currency='USD',value='1000')]
            async def reqExecutionsAsync(self,f):return []
            def reqMarketDataType(self,*a):pass
            def reqMktData(self,c,*a):
                t=NS(contract=c,ticks=[NS(tickType=1),NS(tickType=2)],marketDataType=1,bid=179.,ask=179.1)
                self.pendingTickersEvent.emit([t]);return t
            def placeOrder(self,c,o):
                self.sent+=1;o.clientId=CLIENT_ID
                self.trade=NS(contract=c,order=o,orderStatus=NS(status='Submitted',permId=44,filled=0,remaining=1))
                self.orderStatusEvent.emit(self.trade);return self.trade
            def cancelOrder(self,o):
                self.cancelled+=1;self.trade.orderStatus.status='Cancelled';self.orderStatusEvent.emit(self.trade)
            def cancelMktData(self,*a):pass
            def disconnect(self):self.closed=True
        fake=Fake()
        library=NS(IB=lambda:fake,Stock=lambda *a:None,LimitOrder=lambda side,qty,limit,**k:NS(action=side,totalQuantity=qty,lmtPrice=limit,**k),StartupFetchNONE=0,ExecutionFilter=lambda **k:NS(**k))
        with patch.dict(sys.modules,ib_async=library),patch.object(runner,'STATE_ROOT',self.root),patch.object(runner,'context',return_value=actual),contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(runner.run('cancel'))
            with self.assertRaises(PermissionError):asyncio.run(runner.run('cancel'))
        self.assertEqual(fake.sent,1);self.assertEqual(fake.cancelled,1);self.assertTrue(fake.closed)
        journal=Journal(self.root/'trading_audit.sqlite3',self.j.scope_id)
        self.assertEqual(journal.read('cancel')['status'],'CANCELLED')

    def test_native_outcomes_need_executions_and_position_readback(self):
        from trading.paper_acceptance import reconciled_outcome
        def result(native,**updates):
            d=dict(filled=0,open_count=0,before=0,after=0,side='BUY');d.update(updates)
            return reconciled_outcome(native,**d)
        self.assertEqual(result('Cancelled'),'CANCELLED')
        self.assertEqual(result('Cancelled',rejected=True),'REJECTED')
        self.assertEqual(result('Filled',filled=1,after=1),'FILLED')
        self.assertEqual(result('Filled',filled=1),'UNKNOWN')
        self.assertEqual(result('Filled',after=1),'UNKNOWN')
        self.assertEqual(result('Cancelled',filled=.5,after=.5),'UNKNOWN')
        self.assertEqual(result('Cancelled',open_count=1),'UNKNOWN')
        self.assertEqual(result('Filled',filled=1,before=1,after=0,side='SELL'),'FILLED')
