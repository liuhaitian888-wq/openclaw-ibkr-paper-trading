from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3,tempfile,unittest
from trading.cash_guard import enforce
from trading.models import TradeProposal

class CashGuardTests(unittest.TestCase):
    def run_guard(self,cash,*,reserve=2,age=1,orders=None,delete_policy=False,unit='USD',settled=None,missing_settlement=False,future_settled=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);r=root/'runtime';r.mkdir();(r/'FUNDING_POLICY_REQUIRED').touch()
            policy={'approved':True,'environment':'PAPER','account':'DUQ503649','mode':'CASH_ONLY_NO_NEW_BORROWING','allow_new_currency_debit':False,'fee_reserve_usd':reserve}
            if not delete_policy:(r/'funding-policy.json').write_text(json.dumps(policy))
            stamp=datetime.fromtimestamp(100-age,timezone.utc).isoformat()
            receipt={'source':'NATIVE_ACCOUNT_UPDATE_MULTI','account':'DUQ503649','request_id':1,'complete':True,'started_at':stamp,'finished_at':stamp,'values':[
                {'key':'AccountReady','value':'true','currency':'','account':'DUQ503649'},
                {'key':'SettledCashByDate','value':'19691231:'+str(cash if settled is None else settled)+('' if future_settled is None else ';19700102:'+str(future_settled)),'currency':'USD','account':'DUQ503649'},
                {'key':'SettledCashByDate','value':'19691231:10000','currency':'EUR','account':'DUQ503649'}]}
            book={'source':'BROKER_API','account':'DUQ503649','base_currency':'EUR','observed_at':stamp,'cash_read_started_at':stamp,'cash_read_finished_at':stamp,'currencies':{'USD':{'amount':str(cash),'currency':unit}}}
            if not missing_settlement:book['settlement_receipt']=receipt
            (r/'currency-book.latest.json').write_text(json.dumps(book))
            with closing(sqlite3.connect(r/'recovery.sqlite3')) as c,c:
                c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)');c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps({'identity':True,'connected':True,'upstream_connected':True,'dirty':False,'ends':['positions','orders','executions','completed_orders'],'last_server_reply':99,'orders':orders or {}}),))
            return enforce(root,TradeProposal('BAC','BUY',1,50,49),now=100)
    def test_own_usd_cash_must_cover_cost_and_all_external_buys(self):
        self.run_guard(52)
        with self.assertRaises(PermissionError):self.run_guard(51.99)
        order={'1':{'side':'BUY','account':'DUQ503649','currency':'USD','order_type':'LMT','remaining':1,'limit_price':49,'status':'Submitted'}}
        with self.assertRaises(PermissionError):self.run_guard(100,orders=order)
    def test_negative_usd_positive_other_funds_never_allow_new_borrowing(self):
        with self.assertRaises(PermissionError):self.run_guard(-69788.65)
    def test_missing_policy_fees_or_stale_book_stay_blocked(self):
        for kwargs in ({'delete_policy':True},{'reserve':None},{'reserve':0},{'age':11}):
            with self.subTest(kwargs=kwargs),self.assertRaises(PermissionError):self.run_guard(100,**kwargs)

    def test_wrong_or_missing_currency_unit_cannot_be_spent_as_usd(self):
        for unit in ('EUR',None):
            with self.subTest(unit=unit),self.assertRaises(PermissionError):self.run_guard(10000,unit=unit)

    def test_positive_trade_cash_cannot_hide_unsettled_usd_or_scheduled_debits(self):
        for kwargs in ({'settled':-69788.66},{'missing_settlement':True},{'settled':10000,'future_settled':1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(PermissionError):self.run_guard(2019.4231,**kwargs)
