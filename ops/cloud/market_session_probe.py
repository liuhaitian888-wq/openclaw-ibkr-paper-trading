"""One bounded diagnostic connection reusing T4-v2; never a production owner."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from trading.paper_safety_client import PaperSafetyClient
from trading.paper_safety_monitor import PaperSafetyMonitor,ACCOUNT
from trading.paper_strategy_observer import PaperStrategyObserver
from trading.tws_paper import _close_owned_client
from trading.symbol_health import classify_symbol,session_for_symbol

class DiagnosticClient(PaperSafetyClient):
    def __init__(self,monitor,symbols,path):
        super().__init__(monitor,symbols);self.path=path;self.log_lock=threading.Lock();self.events=0;self.raw_prices={}
    def record(self,kind,payload):
        with self.log_lock:
            if self.events>=100000:raise RuntimeError('Bounded diagnostic event limit')
            self.events+=1
            with self.path.open('a') as f:f.write(json.dumps(dict(received_at=time.time(),kind=kind,payload=payload),default=str)+'\n')
    def placeOrder(self,*args,**kwargs):raise PermissionError('Read-only diagnostic forbids orders')
    def cancelOrder(self,*args,**kwargs):raise PermissionError('Read-only diagnostic forbids order cancellation')
    def reqGlobalCancel(self,*args,**kwargs):raise PermissionError('Read-only diagnostic forbids global cancellation')
    def marketDataType(self,reqId,kind):
        self.record('marketDataType',dict(request_id=reqId,actual_type=kind,requested_type=1));super().marketDataType(reqId,kind)
    def tickPrice(self,reqId,tickType,price,attrib):
        names={1:'bid',2:'ask',4:'last',66:'delayed_bid',67:'delayed_ask',68:'delayed_last'}
        if tickType in names:
            name=names[tickType];self.raw_prices.setdefault(reqId,{}).update({name:price,name+'_received_at':time.time()})
        self.record('tickPrice',dict(request_id=reqId,tick_type=tickType,price=price,symbol=self.tickers.get(reqId),past_limit=getattr(attrib,'pastLimit',None)))
        super().tickPrice(reqId,tickType,price,attrib)
    def tickString(self,reqId,tickType,value):
        if tickType in (45,88):self.raw_prices.setdefault(reqId,{})['broker_last_timestamp' if tickType==45 else 'delayed_broker_last_timestamp']=value
        self.record('tickString',dict(request_id=reqId,tick_type=tickType,value=value,symbol=self.tickers.get(reqId)))
    def realtimeBar(self,reqId,*args):
        self.record('realtimeBar',dict(request_id=reqId,values=args,symbol=self.bar_tickers.get(reqId)));super().realtimeBar(reqId,*args)
    def historicalData(self,reqId,bar):
        self.record('historicalData',dict(request_id=reqId,symbol=self.history_tickers.get(reqId),date=bar.date,open=bar.open,high=bar.high,low=bar.low,close=bar.close,volume=bar.volume))
        super().historicalData(reqId,bar)
    def historicalDataEnd(self,reqId,start,end):
        self.record('historicalDataEnd',dict(request_id=reqId,start=start,end=end));super().historicalDataEnd(reqId,start,end)
    def error(self,reqId,*args):
        self.record('error',dict(request_id=reqId,arguments=args));super().error(reqId,*args)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--production-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=90)
    a=p.parse_args();root=a.production_root.resolve(strict=True);out=a.output.resolve()
    if not 5<=a.seconds<=120 or out==root or root in out.parents or out in root.parents:p.error('Bounded duration and isolated output required')
    manifest=json.loads((root/'production.json').read_text())
    if manifest.get('environment')!='PAPER' or manifest.get('account')!=ACCOUNT or manifest.get('market_symbols')!=['PFE','BAC','KO']:raise PermissionError('Exact existing Paper identity/universe required')
    os.umask(0o077);out.mkdir(parents=True,exist_ok=False)
    cfg=manifest['strategy_configuration'];symbols=manifest['market_symbols']
    monitor=PaperSafetyMonitor(out/'audit.sqlite3',out/'recovery.sqlite3',symbols=symbols,required_bars=cfg['slow_window'])
    observer=PaperStrategyObserver(symbols,cfg,out/'observer.json')
    client=DiagnosticClient(monitor,symbols,out/'raw-callbacks.jsonl');client.strategy_observer=observer;worker=None;grants=[]
    started=time.time()
    try:
        client.connect('127.0.0.1',4002,clientId=18891)
        worker=threading.Thread(target=client.run_loop,name='bounded-market-diagnostic',daemon=True);worker.start()
        if not client.ready.wait(10) or not client.accounts_ready.wait(10) or client.accounts!=[ACCOUNT]:raise PermissionError('Exact Paper handshake failed')
        monitor.begin(client.accounts);grants=client.subscribe()
        deadline=time.monotonic()+a.seconds
        while time.monotonic()<deadline and worker.is_alive():time.sleep(.5)
    finally:
        if client.isConnected():
            for i in client.tickers:client.cancelMktData(i)
            for i in client.bar_tickers:client.cancelRealTimeBars(i)
            for i in client.history_tickers:client.cancelHistoricalData(i)
        _close_owned_client(client,worker)
    now=time.time();result=dict(source='REAL_IBKR_BOUNDED_DIAGNOSTIC',started_at=started,ended_at=now,account=client.accounts,
        production_state_written=False,orders_sent=0,recovery_controller=False,automatic_retries=0,subscriptions=grants,
        disconnected=not client.isConnected(),worker_stopped=not worker or not worker.is_alive(),symbols={})
    for s in symbols:
        i=next(i for i,x in client.tickers.items() if x==s)
        result['symbols'][s]=dict(quote=client.fields.get(i,{}),raw_prices=client.raw_prices.get(i,{}),health=classify_symbol(client.fields.get(i,{}),now,session=session_for_symbol(now)),
            historical_bars=[asdict(b) for b in observer.bars[s].values()],history_complete=s in observer.history_complete,
            history_gaps=observer.history_gaps(s,now),complete_realtime_bar_ends=monitor.state['bars'].get(s,[]))
    (out/'summary.json').write_text(json.dumps(result,indent=2,default=str));print(json.dumps(result,default=str))

if __name__=='__main__':main()
