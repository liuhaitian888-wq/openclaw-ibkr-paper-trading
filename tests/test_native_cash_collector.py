from pathlib import Path
import threading
import unittest
from trading.native_cash_collector import NativeCashCollector

ACCOUNT='DUQ503649'

class FakeClient:
    def __init__(self):self.calls=[];self.connected=True;self.accounts=[ACCOUNT]
    def isConnected(self):return self.connected
    def reqAccountUpdatesMulti(self,*args):self.calls.append(('request',*args))
    def cancelAccountUpdatesMulti(self,request):self.calls.append(('cancel',request))

class NativeCashCollectorTests(unittest.TestCase):
    def setUp(self):
        self.now=1794257000.;self.client=FakeClient();self.books=[];self.states=[];self.allowed=True
        self.collector=NativeCashCollector(self.client,account=ACCOUNT,connection_generation='owned-connection',
            admitted=lambda:self.allowed,publish=self.books.append,
            observe=lambda state,reason,**metadata:self.states.append((state,reason,metadata)),clock=lambda:self.now,monotonic=lambda:self.now)
    def start(self):
        self.collector.poll();return self.client.calls[-1][1]
    def rows(self):
        return [('AccountReady','true',''),('AvailableFunds','990000','EUR'),
                ('$LEDGER-CashBalance','2019.4231','USD'),('$LEDGER-CashBalance','943040.605','EUR'),
                ('$LEDGER-ExchangeRate','.8910311','USD'),('TotalCashValue','944839.97','EUR'),
                ('SettledCashByDate','20261109:-69788.66;20261112:2019.42306','USD'),
                ('SettledCashByDate','20261109:1007454.60504;20261112:943040.60504','EUR')]
    def feed(self,request,rows=None):
        for key,value,currency in self.rows() if rows is None else rows:
            self.collector.value(request,ACCOUNT,'',key,value,currency)
    def test_single_request_exact_end_and_own_cancellation_before_publish(self):
        request=self.start();self.collector.poll();self.feed(request)
        self.collector.end(request+1);self.assertEqual(self.books,[])
        def publish(book):
            self.assertEqual(self.client.calls[-1],('cancel',request));self.books.append(book)
        self.collector.publish=publish
        self.now+=.2;self.collector.end(request)
        self.assertEqual(len(self.books),1);self.assertEqual(len([c for c in self.client.calls if c[0]=='request']),1)
        b=self.books[0];self.assertEqual(b['currencies']['USD']['amount'],'2019.4231')
        self.assertEqual(b['settlement_receipt']['values'][0]['key'],'AccountReady')
        self.assertFalse(b['grants_trading_permission']);self.assertEqual(b['connection_generation'],'owned-connection')
        self.assertEqual(b['requested_currencies'],['USD','EUR'])
        self.assertEqual(self.states[-1][0],'HEALTHY')
    def test_foreign_late_callbacks_and_closed_owner_never_publish(self):
        request=self.start();self.feed(request+1);self.collector.end(request+1)
        self.assertEqual(self.books,[]);self.collector.close();self.feed(request);self.collector.end(request)
        self.collector.poll();self.assertEqual(self.books,[])
        self.assertEqual(len([c for c in self.client.calls if c[0]=='request']),1)
    def test_identity_or_native_admission_failure_never_starts_request(self):
        self.allowed=False;self.collector.poll();self.assertEqual(self.client.calls,[])
        self.allowed=True;self.client.accounts=['OTHER'];self.collector.poll();self.assertEqual(self.client.calls,[])
    def test_negative_settlement_is_complete_data_without_spending_permission(self):
        request=self.start();self.feed(request);self.now+=.1;self.collector.end(request)
        self.assertEqual(len(self.books),1)
        self.assertIn('20261109:-69788.66',next(r['value'] for r in self.books[0]['settlement_receipt']['values'] if r['key']=='SettledCashByDate' and r['currency']=='USD'))
        self.assertFalse(self.books[0]['grants_trading_permission'])
    def test_missing_currency_not_ready_conflicts_and_oversize_do_not_publish(self):
        variants=[[(k,v,c) for k,v,c in self.rows() if c!='USD'],
                  [('AccountReady','false','')]+self.rows()[1:],
                  self.rows()+[('$LEDGER-CashBalance','9999','USD')],
                  self.rows()+[('SettledCashByDate','x'*5001,'USD')]]
        for rows in variants:
            with self.subTest(rows=len(rows)):
                self.setUp();request=self.start();self.feed(request,rows);self.collector.end(request)
                self.assertEqual(self.books,[]);self.assertEqual(self.client.calls[-1],('cancel',request))
                self.assertEqual(self.states[-1][0],'DEGRADED')
    def test_timeout_cancels_owned_request_and_prevents_another_until_reconnect(self):
        request=self.start();self.now+=8.1
        with self.assertRaises(RuntimeError):self.collector.poll()
        self.assertEqual(self.client.calls[-1],('cancel',request))
        self.collector.end(request);self.assertEqual(self.books,[])
        with self.assertRaises(RuntimeError):self.collector.poll()
    def test_publisher_failure_keeps_last_book_and_reports_failure(self):
        request=self.start();self.feed(request)
        def fail(book):raise OSError('Fixture disk unavailable')
        self.collector.publish=fail;self.collector.end(request)
        self.assertEqual(self.books,[]);self.assertEqual(self.states[-1][0],'DEGRADED')
        self.assertEqual(self.client.calls[-1],('cancel',request))
    def test_repeated_cycles_have_no_duplicate_request_thread_or_worker(self):
        before=threading.active_count()
        for _ in range(200):
            request=self.start();self.feed(request);self.now+=.1;self.collector.end(request);self.now+=5
        self.collector.close();self.assertEqual(threading.active_count(),before)
        self.assertEqual(len(self.books),200)
        self.assertEqual(len([c for c in self.client.calls if c[0]=='request']),200)
        self.assertEqual(len([c for c in self.client.calls if c[0]=='cancel']),200)

    def test_cancel_exception_does_not_publish_or_allow_another_subscription(self):
        request=self.start();self.feed(request)
        def fail(request):raise OSError('Fixture cancel failure')
        self.client.cancelAccountUpdatesMulti=fail
        self.collector.end(request);self.assertEqual(self.books,[])
        with self.assertRaises(RuntimeError):self.collector.poll()
    def test_native_send_exception_cancels_owned_id_and_requires_reconnect(self):
        def fail(*args):self.client.calls.append(('request',*args));raise OSError('Fixture send outcome unknown')
        self.client.reqAccountUpdatesMulti=fail
        with self.assertRaises(RuntimeError):self.collector.poll()
        request=self.client.calls[0][1];self.assertEqual(self.client.calls[-1],('cancel',request))
        with self.assertRaises(RuntimeError):self.collector.poll()
    def test_account_change_during_request_is_rejected_at_end(self):
        request=self.start();self.feed(request);self.allowed=False;self.collector.end(request)
        self.assertEqual(self.books,[]);self.assertEqual(self.client.calls[-1],('cancel',request))
