"""Read-only monitoring adapter over existing order callbacks; never submits."""
from datetime import datetime, timezone
import time
import math
import uuid
from trading.tws_paper import TwsPaperClient


class PaperSafetyClient(TwsPaperClient):
    def __init__(self, monitor, symbols, *, bar_wire_protocol='auto',cashbook_publisher=None):
        if bar_wire_protocol not in ('auto','legacy'):raise ValueError('Explicit supported bar protocol required')
        self.bar_wire_protocol=bar_wire_protocol
        super().__init__()
        self.monitor = monitor
        self.connection_generation=uuid.uuid4().hex
        self.upstream_reported_lost=False
        self._initial_pending=set()
        self.tickers = {46000+i:s for i,s in enumerate(symbols)}
        self.bar_tickers = {47000+i:s for i,s in enumerate(symbols)}
        self.fields, self.bar_parts = {}, {}
        self.strategy_observer = None
        self.history_tickers = {49000+i:s for i,s in enumerate(symbols)}
        self.read_only_completed_orders_blocked = False
        self._history_gap_pending=set()
        self.research_scanner = None
        self._cash_request_sequence=0
        self.cashbook_publisher=cashbook_publisher
        self.cashbook_collector=None
        self._reset_cashbook_collector()

    def useProtoBuf(self,msgId):
        from ibapi.message import OUT
        bars=(OUT.REQ_HISTORICAL_DATA,OUT.CANCEL_HISTORICAL_DATA,OUT.REQ_REAL_TIME_BARS,OUT.CANCEL_REAL_TIME_BARS)
        if self.bar_wire_protocol=='legacy' and msgId in bars:return False
        return super().useProtoBuf(msgId)

    def connect(self,*args,**kwargs):
        if not self.isConnected():
            self.connection_generation=uuid.uuid4().hex
            self._initial_pending.clear()
            self.upstream_reported_lost=False
            self._reset_cashbook_collector()
        return super().connect(*args,**kwargs)

    def _next_cash_request_id(self):
        # Keep request identity unique even when the same EWrapper reconnects.
        self._cash_request_sequence+=1
        return 800000000+self._cash_request_sequence

    def _cashbook_admitted(self):
        with self.monitor.lock:
            return self.monitor._complete() and self.monitor.state.get('api_protocol',{}).get('connection')==self.connection_generation

    def _observe_cashbook(self,state,reason,**metadata):
        self.monitor.coordinator.observe('CURRENCY_BOOK',state,reason=reason,
            freshness='FRESH' if state=='HEALTHY' else 'STALE',**metadata)

    def _reset_cashbook_collector(self):
        if self.cashbook_collector is not None:self.cashbook_collector.close()
        if self.cashbook_publisher is None:return
        from trading.native_cash_collector import NativeCashCollector
        self.cashbook_collector=NativeCashCollector(self,account='DUQ503649',connection_generation=self.connection_generation,
            admitted=self._cashbook_admitted,publish=self.cashbook_publisher,observe=self._observe_cashbook,clock=self.monitor.clock,allocate_request_id=self._next_cash_request_id)
        self._observe_cashbook('DEGRADED','Awaiting complete owned native cash request',enabled=True,grants_trading_permission=False)

    def poll_cashbook(self):
        if self.cashbook_collector is not None:self.cashbook_collector.poll()

    def close_cashbook(self):
        if self.cashbook_collector is not None:self.cashbook_collector.close()

    def accountUpdateMulti(self,reqId,account,modelCode,key,value,currency):
        if self.cashbook_collector is not None:self.cashbook_collector.value(reqId,account,modelCode,key,value,currency)

    def accountUpdateMultiEnd(self,reqId):
        if self.cashbook_collector is not None:self.cashbook_collector.end(reqId)

    def nextValidId(self, orderId):
        super().nextValidId(orderId)
        from ibapi.message import OUT
        with self.monitor.lock:
            self.monitor.state['bar_callback_diagnostics']={}
            self.monitor.state['api_protocol']=dict(connection=self.connection_generation,
                server_version=self.serverVersion(),observed_at=self.monitor.clock(),configured_bar_protocol=self.bar_wire_protocol,
                history_protobuf=self.useProtoBuf(OUT.REQ_HISTORICAL_DATA),
                realtime_bars_protobuf=self.useProtoBuf(OUT.REQ_REAL_TIME_BARS))

    def _bar_callback(self,kind,req_id,raw_time):
        symbol=self.history_tickers.get(req_id) or self.bar_tickers.get(req_id) or '@unknown'
        with self.monitor.lock:
            rows=self.monitor.state.setdefault('bar_callback_diagnostics',{})
            key=kind+':'+symbol
            row=rows.get(key,{})
            count=row.get('count',0) if row.get('connection')==self.connection_generation else 0
            rows[key]=dict(count=count+1,request_id=req_id,raw_time=str(raw_time),
                received_at=self.monitor.clock(),connection=self.connection_generation)

    def historicalDataUpdateProtoBuf(self, message):
        bar=getattr(message,'historicalDataBar',None)
        self._bar_callback('history_update_protobuf',getattr(message,'reqId',0),getattr(bar,'date',''))

    def realTimeBarTickProtoBuf(self, message):
        self._bar_callback('realtime_bar_protobuf',getattr(message,'reqId',0),getattr(message,'time',''))

    def connectionClosed(self):
        self.monitor.invalidate('API_CONNECTION_CLOSED')

    def currentTime(self, timestamp):
        with self.monitor.lock:
            self.monitor.state['last_server_reply'] = self.monitor.clock()
            self.monitor._publish()

    def error(self, reqId, *args):
        super().error(reqId, *args)
        code = args[1] if len(args)>1 and isinstance(args[0],int) and args[0]>10**10 else args[0] if args else None
        if self.research_scanner is not None and self.research_scanner.error(reqId,code):return
        if isinstance(code,int):
            if code in (10197,1100,1101,1102,2110,162,321,101,10225,354,10168,10186) or reqId in self.bar_tickers or reqId in self.history_tickers:
                self.monitor._record('error',dict(request_id=reqId,code=code,details=str(args)))
            symbol=self.tickers.get(reqId) or self.bar_tickers.get(reqId) or self.history_tickers.get(reqId)
            if symbol:
                self.monitor.market_error(symbol,code,str(args))
            elif code in (1100,1101,1102):
                for affected in self.monitor.symbols:self.monitor.market_error(affected,code,str(args))
            with self.monitor.lock:
                if code in (1100,2110):self.upstream_reported_lost=True
                elif code in (1101,1102):self.upstream_reported_lost=False
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

    def scannerData(self, reqId, rank, contractDetails, distance, benchmark, projection, legsStr):
        if self.research_scanner is not None:self.research_scanner.data(reqId,rank,contractDetails)

    def scannerDataEnd(self, reqId):
        if self.research_scanner is not None:self.research_scanner.end(reqId)

    def openOrder(self, orderId, contract, order, orderState):
        super().openOrder(orderId, contract, order, orderState)
        payload = dict(self.broker_orders[orderId])
        details = self.order_status_details.get(orderId,{})
        payload.update(details)
        # Never infer remaining from total quantity before a broker status.
        self.monitor.order(payload)

    def completedOrder(self, contract, order, orderState):
        # Completed-order callbacks may all expose orderId=0 after Gateway restart.
        # Do not overwrite the active client's orderId lookup with those records.
        payload=self._order_payload(int(getattr(order,'orderId',0)),contract,order,orderState,completed=True)
        self.monitor.order(payload)

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
            evidence=dict(self.executions[key],con_id=getattr(contract,'conId',0),
                          currency=getattr(contract,'currency',''),sec_type=getattr(contract,'secType',''))
            self.executions[key]=evidence
            self.monitor.execution(evidence)

    def commissionReport(self, report):
        amount=getattr(report,'commission',None)
        # Legacy decoder also maps an empty wire amount to zero; no presence proof is available.
        if amount==0:amount=None
        self.monitor.execution_fee(str(getattr(report,'execId','')),str(getattr(report,'currency','')),
                                   amount,'commissionReport')

    def commissionAndFeesReportProtoBuf(self, message):
        # The SDK immediately emits a normalized callback, defaulting an absent fee to 0.
        # Preserve presence so missing protobuf data cannot become an explicit zero fee.
        self._fee_proto_presence=(str(getattr(message,'execId','')),all(message.HasField(k) for k in ('execId','currency','commissionAndFees')))

    def commissionAndFeesReport(self, report):
        presence=getattr(self,'_fee_proto_presence',None)
        native_id=str(getattr(report,'execId',''));source='commissionAndFeesReport'
        amount=getattr(report,'commissionAndFees',None)
        if presence and presence[0]==native_id:
            self._fee_proto_presence=None;source='commissionAndFeesReportProtoBuf'
            if not presence[1]:amount=None
        elif amount==0:
            amount=None # A legacy normalized zero cannot prove that the native field was present.
        self.monitor.execution_fee(native_id,str(getattr(report,'currency','')),amount,source)

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
        if 'quotes' in streams:self.monitor.symbol_recovery.invalidate_evidence(symbol)
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
                with self.monitor.lock:
                    self.monitor.state.setdefault('history_evidence',{}).pop(symbol,None)
                    self.monitor.state.setdefault('history_request_started',{})[symbol]=self.monitor.clock()
                    self.monitor._publish()
                self.reqHistoricalData(req_id,self._contract(symbol),'','1800 S','1 min','TRADES',1,2,True,[])
        except Exception:
            lifecycle.finish(grant,sent=False)
            raise
        lifecycle.finish(grant,sent=True)
        return grant

    def retry_symbol_subscriptions(self, symbols, *, bars_only=False, low_frequency=False):
        streams=('bars',) if bars_only else ('quotes','bars','history') if self.strategy_observer else ('quotes','bars')
        return [self._admitted_subscription(symbol,streams,'LOW_FREQUENCY_RECOVERY' if low_frequency else 'RECOVERY') for symbol in symbols]

    def realtimeBar(self, reqId, timestamp, open_, high, low, close, volume, wap, count):
        self._bar_callback('realtime_bar_legacy',reqId,timestamp)
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
            gaps=self.strategy_observer.history_gaps(symbol,self.monitor.clock())
        with self.monitor.lock:
            self.monitor.state.setdefault('history_evidence',{})[symbol]=dict(
                completed_ends=ends[-self.monitor.required_bars:],complete=complete,received_at=self.monitor.clock())
            self.monitor._publish()
        tail=ends[-self.monitor.required_bars:]
        if (complete and not gaps and len(tail)>=self.monitor.required_bars and all(b-a==60 for a,b in zip(tail,tail[1:]))
                and 0<=self.monitor.clock()-tail[-1]<=65):
            self.monitor.symbol_recovery.lifecycle.validated(symbol,evidence_streams=('history',))

    def historicalDataUpdate(self, reqId, bar):
        self._bar_callback('history_update_legacy',reqId,getattr(bar,'date',''))
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
        if not self.strategy_observer or not all(self.monitor.state.get(k) for k in ('upstream_connected','connected','identity')):
            return results
        warmup=set()
        now=self.monitor.clock()
        for symbol in self.history_tickers.values():
            with self.strategy_observer.lock:
                incomplete=(symbol not in self.strategy_observer.history_complete or
                    len(self.strategy_observer.bars.get(symbol,{}))<self.monitor.required_bars)
            proof=self.monitor.symbol_recovery.snapshot(symbol)
            health=proof.get('health',{})
            started=self.monitor.state.get('history_request_started',{}).get(symbol,self.monitor.state['reset_at'])
            if (incomplete and now-started>=30 and proof.get('phase')=='NORMAL' and not proof.get('fault_active',True)
                    and proof.get('validations',0)>=self.monitor.symbol_recovery.validations
                    and health.get('allows_realtime') is True and 0<=now-health.get('observed_at',0)<=5):
                warmup.add(symbol);self._history_gap_pending.add(symbol)
        for symbol in tuple(self._history_gap_pending):
            with self.strategy_observer.lock:
                gaps=self.strategy_observer.history_gaps(symbol,self.monitor.clock())
            if not gaps and symbol not in warmup:
                self._history_gap_pending.discard(symbol)
                continue
            result=self._admitted_subscription(symbol,('history',),'HISTORY_RECOVERY' if symbol in warmup and not gaps else 'HISTORY_GAP')
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
