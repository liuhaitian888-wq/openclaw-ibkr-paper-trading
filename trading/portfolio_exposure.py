"""Conservative USD portfolio marks for additive caps; missing marks fail closed."""
from contextlib import closing
import json
import math
import sqlite3
import time
from pathlib import Path


def measured_exposure(root,symbol,*,now=None):
    now=time.time() if now is None else now
    path=Path(root)/'runtime/recovery.sqlite3'
    try:
        with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True,timeout=.2)) as c:
            c.execute('PRAGMA query_only=ON');deadline=time.monotonic()+.2;c.set_progress_handler(lambda:int(time.monotonic()>deadline),500)
            row=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        s=json.loads(row[0]) if row else {}
        def number(v):return type(v) in (int,float) and math.isfinite(v)
        if not (s.get('identity') is True and s.get('connected') is True and s.get('upstream_connected') is True and s.get('dirty') is False
                and set(s.get('ends',[]))=={'positions','orders','completed_orders','executions'}
                and number(s.get('last_server_reply')) and 0<=now-s['last_server_reply']<=10):
            raise ValueError('Fresh complete Paper portfolio required')
        amounts={};positions=s.get('positions',{})
        for ticker,qty in positions.items():
            if not number(qty):raise ValueError('Invalid broker position')
            if not qty:continue
            contract=s.get('contracts',{}).get(ticker,{})
            q=s.get('quotes',{}).get(ticker,{})
            bid,ask=q.get('bid'),q.get('ask')
            if not (contract.get('currency')=='USD' and contract.get('sec_type')=='STK' and contract.get('con_id')
                    and number(bid) and number(ask) and 0<bid<=ask and q.get('data_type')==1
                    and all(number(q.get(k)) and 0<=now-q[k]<=5 for k in ('bid_at','ask_at'))):
                raise ValueError('Fresh USD mark unavailable for '+ticker)
            amounts[ticker]=abs(qty)*ask
        sells={}
        for o in s.get('orders',{}).values():
            if o.get('completed') or o.get('status') in ('Filled','Cancelled','ApiCancelled','Inactive'):continue
            ticker=o.get('symbol');qty=o.get('remaining')
            if o.get('account')!='DUQ503649' or o.get('currency')!='USD' or o.get('sec_type')!='STK' or not number(qty) or qty<0:
                raise ValueError('Unbounded external order exposure')
            if o.get('side')=='BUY':
                price=o.get('limit_price')
                if o.get('order_type')!='LMT' or not number(price) or price<=0:raise ValueError('Unbounded external buy')
                amounts[ticker]=amounts.get(ticker,0)+qty*price
            elif o.get('side')=='SELL':
                sells[ticker]=sells.get(ticker,0)+qty
                if sells[ticker]>max(0,positions.get(ticker,0)):raise ValueError('Potential external short exposure')
            else:raise ValueError('Unknown external order side')
        return amounts.get(symbol,0),sum(amounts.values())
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
        raise PermissionError('Portfolio exposure unverified; additive caps fail closed: '+str(exc)) from exc
