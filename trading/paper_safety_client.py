"""Read-only monitoring adapter over existing order callbacks; never submits."""
from datetime import datetime, timezone
import time
import math
from trading.tws_paper import TwsPaperClient


class PaperSafetyClient(TwsPaperClient):
    def __init__(self, monitor, symbols):
        super().__init__()
        self.monitor = monitor
        self.tickers = {46000+i:s for i,s in enumerate(symbols)}
        self.bar_tickers = {47000+i:s for i,s in enumerate(symbols)}
        self.fields, self.bar_parts = {}, {}

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
            self.monitor.error(code)
            if reqId in self.tickers and code not in (2104,2106,2107,2108,2158):
                with self.monitor.lock:
                    self.monitor.state['quotes'].pop(self.tickers[reqId],None)
                    self.monitor._publish()
        if code in (326, 101):
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

    def tickPrice(self, reqId, tickType, price, attrib):
        if reqId not in self.tickers or tickType not in (1,2):
            return
        key = 'bid' if tickType==1 else 'ask'
        fields = self.fields.setdefault(reqId,{})
        fields[key], fields[key+'_at'] = price, self.monitor.clock()
        self.monitor.quote(self.tickers[reqId], fields.get('bid'),fields.get('ask'),
                           fields.get('bid_at'),fields.get('ask_at'),fields.get('data_type'))

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
        self.fields.clear()
        self.bar_parts.clear()
        self.reqMarketDataType(1)
        for req_id,symbol in self.tickers.items():
            self.reqMktData(req_id,self._contract(symbol),'',False,False,[])
        for req_id,symbol in self.bar_tickers.items():
            self.reqRealTimeBars(req_id,self._contract(symbol),5,'TRADES',True,[])

    def retry_subscriptions(self):
        # Cancellation applies exclusively to our data subscriptions, never orders.
        for req_id in self.tickers:
            self.cancelMktData(req_id)
        for req_id in self.bar_tickers:
            self.cancelRealTimeBars(req_id)
        self.subscribe()

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
