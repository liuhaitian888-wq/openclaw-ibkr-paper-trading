"""Read-only monitoring adapter over existing order callbacks; never submits."""
from datetime import datetime, timezone
import time
import math
import uuid
from trading.tws_paper import TwsPaperClient


class PaperSafetyClient(TwsPaperClient):
    def __init__(self, monitor, symbols):
        super().__init__()
        self.monitor = monitor
        self.connection_generation=uuid.uuid4().hex
        self._initial_pending=set()
        self.tickers = {46000+i:s for i,s in enumerate(symbols)}
        self.bar_tickers = {47000+i:s for i,s in enumerate(symbols)}
        self.fields, self.bar_parts = {}, {}
        self.strategy_observer = None
        self.history_tickers = {49000+i:s for i,s in enumerate(symbols)}
        self.read_only_completed_orders_blocked = False
        self._history_gap_pending=set()

    def connect(self,*args,**kwargs):
        if not self.isConnected():
            self.connection_generation=uuid.uuid4().hex
            self._initial_pending.clear()
        return super().connect(*args,**kwargs)

    def connectionClosed(self):
        self.monitor.invalidate('API_CONNECTION_CLOSED')

    def currentTime(self, timestamp):
        with self.monitor.lock:
            self.monitor.state['last_server_reply'] = self.monitor.clock()
            self.monitor._publish()

    def error(self, reqId, *args):
        super().error(reqId, *args)
        code = args[1] if len(args)>1 and isinstance(args[0],int) and args[0]>10**10 else args[0] if args else None
        if isinstance(code,int):
            if code in (10197,1100,1101,1102,162,321,101,10225,354,10168,10186):
                self.monitor._record('error',dict(request_id=reqId,code=code,details=str(args)))
            symbol=self.tickers.get(reqId) or self.bar_tickers.get(reqId) or self.history_tickers.get(reqId)
            if symbol:
                self.monitor.market_error(symbol,code,str(args))
            elif code in (1100,1101,1102):
                for affected in self.monitor.symbols:self.monitor.market_error(affected,code,str(args))
            self.monitor.error(code,symbol=symbol)
            if code==321 and 'read-only' in str(args).lower():
                self.read_only_completed_orders_blocked = True
                with self.monitor.lock:
                    self.monitor.state['fault']='READ_ONLY_COMPLETED_ORDERS_BLOCKED'
                    self.monitor._publish()
            if reqId in self.tickers and code not in (2104,2106,2107,2108,2158):
                with self.monitor.lock:
                    self.monitor.state['quotes'].pop(self.tickers[reqId],None)
                    self.monitor._publish()
        if code == 326:
            self.monitor.invalidate('AUTH_OR_API_CONFIGURATION_REQUIRED')

    def openOrder(self, orderId, contract, order, orderState):
        super().openOrder(orderId, contract, order, orderState)
        payload = dict(self.broker_orders[orderId])
        details = self.order_status_details.get(orderId,{})
        payload.update(details)
        # Never infer remaining from total quantity before a broker status.
        self.monitor.order(payload)

    def completedOrder(self, contract, order, orderState):
        super().completedOrder(contract,order,orderState)
        self.monitor.order(dict(self.broker_orders[int(order.orderId)]))

    def orderStatus(self, orderId, *args):
        super().orderStatus(orderId,*args)
        if orderId in self.broker_orders:
            self.monitor.order(dict(self.broker_orders[orderId]))
        else:
            with self.monitor.lock:
                self.monitor.state.update(dirty=True, fault='ORDER_STATUS_WITHOUT_IDENTITY')
                self.monitor._publish()

    def execDetails(self, reqId, contract, execution):
        super().execDetails(reqId,contract,execution)
        key = str(getattr(execution,'execId',''))
        if key:
            self.monitor.execution(dict(self.executions[key]))

    def position(self, account, contract, quantity, avgCost):
        self.monitor.position(contract.symbol, quantity, account,
                              con_id=getattr(contract,'conId',0),currency=getattr(contract,'currency',''),
                              sec_type=getattr(contract,'secType',''))

    def positionEnd(self):
        self.monitor.end('positions')

    def openOrderEnd(self):
        super().openOrderEnd()
        self.monitor.end('orders')

    def execDetailsEnd(self, reqId):
        super().execDetailsEnd(reqId)
        self.monitor.end('executions')

    def completedOrdersEnd(self):
        super().completedOrdersEnd()
        self.monitor.end('completed_orders')

    def marketDataType(self, reqId, marketDataType):
        self.fields.setdefault(reqId,{})['data_type'] = marketDataType
        if reqId in self.tickers:
            with self.monitor.lock:
                symbol=self.tickers[reqId]
                self.monitor.state['market_types'][symbol]=marketDataType
                if marketDataType==1 and self.monitor.state['market_errors'].get(symbol,{}).get('code') in (354,10168,10186):
                    self.monitor.state['market_errors'].pop(symbol,None)

    def tickPrice(self, reqId, tickType, price, attrib):
        names={1:'bid',2:'ask',4:'last',66:'bid',67:'ask',68:'last'}
        if reqId not in self.tickers or tickType not in names:
            return
        key=names[tickType]
        fields = self.fields.setdefault(reqId,{})
        fields[key], fields[key+'_at'] = price, self.monitor.clock()
        self.monitor.quote(self.tickers[reqId], fields.get('bid'),fields.get('ask'),
                           fields.get('bid_at'),fields.get('ask_at'),fields.get('data_type'),
                           last=fields.get('last'),last_at=fields.get('last_at'),event_time=fields.get('event_time'))

    def tickString(self, reqId, tickType, value):
        if reqId in self.tickers and tickType in (45,88):
            fields=self.fields.setdefault(reqId,{})
            fields['event_time']=str(value)
            with self.monitor.lock:
                self.monitor.state['quotes'].setdefault(self.tickers[reqId],{})['event_time']=str(value)
                self.monitor._publish()

    def tickGeneric(self, reqId, tickType, value):
        if reqId in self.tickers and tickType==49:
            with self.monitor.lock:self.monitor.state['market_halts'][self.tickers[reqId]]=value

    def _admitted_subscription(self,symbol,streams,reason):
        lifecycle=self.monitor.symbol_recovery.lifecycle
        grant=lifecycle.reserve(symbol,streams,self.connection_generation,reason=reason)
        if not grant['allowed']:return grant
        self.monitor.symbol_recovery.invalidate_evidence(symbol)
        try:
            if 'quotes' in streams:self.reqMarketDataType(1)
            if 'bars' in streams:
                self.bar_parts.pop(symbol,None)
                with self.monitor.lock:
                    self.monitor.state['bars'].pop(symbol,None)
                    self.monitor.state['symbol_reset_at'][symbol]=self.monitor.clock()
            if 'quotes' in streams:
                req_id=next(i for i,s in self.tickers.items() if s==symbol)
                if 'quotes' in grant['replaces']:self.cancelMktData(req_id)
                self.fields.pop(req_id,None)
                with self.monitor.lock:
                    self.monitor.state['quotes'].pop(symbol,None)
                    self.monitor.state['market_types'].pop(symbol,None)
                self.reqMktData(req_id,self._contract(symbol),'',False,False,[])
            if 'bars' in streams:
                req_id=next(i for i,s in self.bar_tickers.items() if s==symbol)
                if 'bars' in grant['replaces']:self.cancelRealTimeBars(req_id)
                self.reqRealTimeBars(req_id,self._contract(symbol),5,'TRADES',True,[])
            if 'history' in streams:
                req_id=next(i for i,s in self.history_tickers.items() if s==symbol)
                if 'history' in grant['replaces']:self.cancelHistoricalData(req_id)
                with self.strategy_observer.lock:self.strategy_observer.history_complete.discard(symbol)
                with self.monitor.lock:self.monitor.state.setdefault('history_evidence',{}).pop(symbol,None)
                self.reqHistoricalData(req_id,self._contract(symbol),'','1800 S','1 min','TRADES',1,2,True,[])
        except Exception:
            lifecycle.finish(grant,sent=False)
            raise
        lifecycle.finish(grant,sent=True)
        return grant

    def retry_symbol_subscriptions(self, symbols, *, bars_only=False):
        streams=('bars',) if bars_only else ('quotes','bars','history') if self.strategy_observer else ('quotes','bars')
        return [self._admitted_subscription(symbol,streams,'RECOVERY') for symbol in symbols]

    def realtimeBar(self, reqId, timestamp, open_, high, low, close, volume, wap, count):
        if reqId not in self.bar_tickers:
            return
        symbol = self.bar_tickers[reqId]
        prices = [float(x) for x in (open_,high,low,close)]
        if (not all(math.isfinite(p) and p>0 for p in prices)
                or high < max(open_,close,low) or low > min(open_,close,high)
                or not math.isfinite(float(volume)) or volume < 0):
            return
        start = timestamp - timestamp%60
        parts = self.bar_parts.setdefault(symbol,{})
        for old in list(parts):
            if old < start:
                del parts[old]
        bucket = parts.setdefault(start,set())
        if timestamp%5 or timestamp+5>self.monitor.clock():
            return
        bucket.add(timestamp)
        if bucket==set(range(start,start+60,5)):
            self.monitor.bar(symbol,start,start+60)

    def subscribe(self):
        streams=('quotes','bars','history') if self.strategy_observer else ('quotes','bars')
        results=[self._admitted_subscription(symbol,streams,'INITIAL') for symbol in self.tickers.values()]
        self._initial_pending={symbol for symbol,result in zip(self.tickers.values(),results) if result.get('reason')=='INCIDENT_BACKOFF'}
        return results

    def retry_pending_initial(self):
        streams=('quotes','bars','history') if self.strategy_observer else ('quotes','bars')
        for symbol in tuple(self._initial_pending):
            result=self._admitted_subscription(symbol,streams,'INITIAL')
            if result.get('reason')!='INCIDENT_BACKOFF':self._initial_pending.discard(symbol)

    def historicalData(self, reqId, bar):
        symbol=self.history_tickers.get(reqId)
        if symbol and self.strategy_observer:
            with self.strategy_observer.lock:
                self.strategy_observer.history(symbol,bar,self.monitor.clock())

    def _sync_history_evidence(self, symbol):
        with self.strategy_observer.lock:
            bars=self.strategy_observer.bars[symbol]
            ends=[bars[k].ended_at.timestamp() for k in sorted(bars)]
            complete=symbol in self.strategy_observer.history_complete
        with self.monitor.lock:
            self.monitor.state.setdefault('history_evidence',{})[symbol]=dict(
                completed_ends=ends[-self.monitor.required_bars:],complete=complete,received_at=self.monitor.clock())
            self.monitor._publish()

    def historicalDataUpdate(self, reqId, bar):
        self.historicalData(reqId,bar)
        symbol=self.history_tickers.get(reqId)
        if symbol and self.strategy_observer:
            with self.monitor.lock:
                self.monitor.state.setdefault('history_updates',{})[symbol]=dict(received_at=self.monitor.clock(),bar_start=str(bar.date))
            self._sync_history_evidence(symbol)

    def historicalDataEnd(self, reqId, start, end):
        if reqId in self.history_tickers and self.strategy_observer:
            symbol=self.history_tickers[reqId]
            with self.strategy_observer.lock:
                self.strategy_observer.history_complete.add(symbol)
                gaps=self.strategy_observer.history_gaps(symbol,self.monitor.clock())
            if gaps:self._history_gap_pending.add(symbol)
            else:self._history_gap_pending.discard(symbol)
            self._sync_history_evidence(symbol)

    def backfill_history_gaps(self):
        """Existing owner only; share T4-v2 budget, never resubscribe quote peers."""
        results=[]
        if not self.strategy_observer or not self.monitor.state.get('upstream_connected'):
            return results
        for symbol in tuple(self._history_gap_pending):
            with self.strategy_observer.lock:
                gaps=self.strategy_observer.history_gaps(symbol,self.monitor.clock())
            if not gaps:
                self._history_gap_pending.discard(symbol)
                continue
            result=self._admitted_subscription(symbol,('history',),'HISTORY_GAP')
            results.append(result)
            self.monitor._record('history_gap',dict(symbol=symbol,missing_starts=gaps,decision=result))
            if result.get('reason') in ('INCIDENT_BUDGET_EXHAUSTED','PENDING_OR_UNKNOWN_REQUEST'):
                self._history_gap_pending.discard(symbol)
        return results

    def retry_subscriptions(self):
        # Legacy callers use the same durable admission; no cancellation before it.
        return self.retry_symbol_subscriptions(tuple(self.tickers.values()))

    def recover_data_if_required(self):
        # Called only by the existing single service owner, never a timer/thread.
        with self.monitor.lock:
            required = self.monitor.state.get('resubscribe_required',False)
            if not required:
                return False
        self.retry_subscriptions()
        with self.monitor.lock:
            self.monitor.state['resubscribe_required'] = False
        return True

    def reconcile(self):
        from ibapi.execution import ExecutionFilter
        self.monitor.start_reconciliation()
        self.reqAllOpenOrders()
        self.reqCompletedOrders(False)
        self.reqExecutions(48000, ExecutionFilter())
        self.reqPositions()

    @staticmethod
    def _contract(symbol):
        from ibapi.contract import Contract
        contract=Contract()
        contract.symbol,contract.secType,contract.exchange,contract.currency=symbol,'STK','SMART','USD'
        return contract
