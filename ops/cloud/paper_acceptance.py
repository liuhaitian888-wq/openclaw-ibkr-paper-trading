"""Finite user-approved real Paper order test. No daemon or order replay."""
import argparse
import asyncio
from datetime import datetime,timezone
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
import json
import math
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from trading.paper_acceptance import ACCOUNT,CLIENT_ID,Journal,validate_scope,check_order,owned_order,stamp,check_session,reconciled_outcome
from trading.production_paths import STATE_ROOT
from trading.production_diagnostics import context
from reporting.recovery import RecoveryCoordinator
from trading.currency_book import cashbook,paper_funding
from ops.cloud.monitoring_guard import monitoring_service


async def wait_until(condition,seconds=20):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if condition():return True
        await asyncio.sleep(.1)
    return False


async def run(stage):
    from ib_async import IB,Stock,LimitOrder,StartupFetchNONE,ExecutionFilter
    root=STATE_ROOT
    scope=json.loads((root/'runtime/paper-acceptance-scope.json').read_text())
    validate_scope(scope,context(),root)
    journal=Journal(root/'trading_audit.sqlite3',scope['id'])
    coordinator=RecoveryCoordinator(root/'runtime/recovery.sqlite3')
    ib=IB();contract=None;ref=None;trade=None;subscribed=False
    errors=[];times={};quote_times={}
    def error(req,code,message,*args):
        row=dict(request_id=req,code=code,message=message,received_at=stamp());errors.append(row)
        if ref:journal.event(ref,'BROKER_ERROR',row)
    ib.errorEvent+=error
    def price(tickers):
        for t in tickers:
            if contract is not None and t.contract.conId==contract.conId:
                for tick in t.ticks:
                    if tick.tickType in (1,2):quote_times['bid' if tick.tickType==1 else 'ask']=time.time()
    ib.pendingTickersEvent+=price
    try:
        await ib.connectAsync('127.0.0.1',4002,clientId=CLIENT_ID,readonly=True,fetchFields=StartupFetchNONE,timeout=8)
        if ib.managedAccounts()!=[ACCOUNT]:raise PermissionError('Exact Paper identity required')
        contracts=await asyncio.wait_for(ib.qualifyContractsAsync(Stock('NVDA','SMART','USD')),8)
        if len(contracts)!=1:raise PermissionError('Contract not uniquely resolved')
        contract=contracts[0]
        details=await asyncio.wait_for(ib.reqContractDetailsAsync(contract),8)
        if not details or details[0].minTick<=0:raise PermissionError('Broker minTick unavailable')
        # These are real snapshots with end markers, not cached baseline projections.
        check_session(details[0].tradingHours,details[0].timeZoneId)
        positions=await asyncio.wait_for(ib.reqPositionsAsync(),8)
        opens=await asyncio.wait_for(ib.reqAllOpenOrdersAsync(),8)
        values=await asyncio.wait_for(ib.accountSummaryAsync(ACCOUNT),8)
        executions=await asyncio.wait_for(ib.reqExecutionsAsync(ExecutionFilter(acctCode=ACCOUNT)),8)
        position=sum(float(p.position) for p in positions if p.account==ACCOUNT and p.contract.conId==contract.conId)
        if any(p.account!=ACCOUNT for p in positions):raise PermissionError('Mixed account snapshot')
        held={p.contract.symbol:float(p.position) for p in positions}
        orders=[dict(account=t.order.account,symbol=t.contract.symbol,currency=t.contract.currency,
            side=t.order.action,order_type=t.order.orderType,remaining=float(t.orderStatus.remaining or t.order.totalQuantity),
            limit=t.order.lmtPrice,held_position=held.get(t.contract.symbol,0),perm_id=t.order.permId,order_ref=t.order.orderRef) for t in opens]
        book=cashbook(values,ACCOUNT)
        funding=paper_funding(book,scope.get('currency_financing_policy','CASH_ONLY'))
        cash=funding['usd_cash'];funds=funding['available_funds_usd']
        ib.reqMarketDataType(1);ticker=ib.reqMktData(contract,'',False,False);subscribed=True
        if not await wait_until(lambda:all(k in quote_times for k in ('bid','ask')) and ticker.marketDataType==1,15):
            raise PermissionError('No fresh real-time bid/ask')
        tick=Decimal(str(details[0].minTick))
        raw=Decimal(str(ticker.bid))*Decimal('.98') if stage=='cancel' else Decimal(str(ticker.bid))-tick*2 if stage=='close' else Decimal(str(ticker.ask))+tick*2
        rounding=ROUND_FLOOR if stage in ('cancel','close') else ROUND_CEILING
        limit=float((raw/tick).to_integral_value(rounding=rounding)*tick)
        intended='fill' if stage=='preflight' else stage
        if any(row[1]=='order' for row in coordinator.uncertainties()):raise PermissionError('Uncertain global operations require reconciliation')
        validate_scope(scope,context(),root)
        plan=check_order(intended,bid=ticker.bid,ask=ticker.ask,bid_at=quote_times['bid'],ask_at=quote_times['ask'],
            data_type=ticker.marketDataType,limit=limit,min_tick=float(tick),position=position,baseline=0,
            usd_cash=cash,available_funds=funds,orders=orders,now=time.time(),funding_capacity_usd=funding['capacity_usd'])
        if stage=='close':
            prior=journal.read('fill')
            if not prior or prior['status']!='FILLED' or not prior.get('exec_ids'):
                raise PermissionError('Test-owned fill proof required before selling')
        report=dict(stage=stage,observed_at=stamp(),account=ACCOUNT,contract_id=contract.conId,bid=ticker.bid,ask=ticker.ask,
            cashbook=book,funding=funding,quote_times=quote_times,trading_hours=details[0].tradingHours,contract_timezone=details[0].timeZoneId,min_tick=float(tick),usd_cash=cash,available_funds=funds,positions=[dict(symbol=p.contract.symbol,quantity=str(p.position)) for p in positions],
            orders=orders,execution_count=len(executions),plan=plan,errors=errors,orders_sent=0,grants_strategy_permission=False)
        evidence=root/'observations/paper-acceptance';evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
        if stage=='preflight':
            (evidence/'preflight.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));return
        existing=journal.read(stage)
        if existing:raise PermissionError('Stage already reserved; readback only, never replay')
        order_id=ib.client.getReqId()
        report.update(order_id=order_id,submission_started_at=stamp())
        ref=journal.reserve(stage,report)
        if not coordinator.begin_operation('order:'+ref,'order',dict(scope=scope['id'],stage=stage,order_id=order_id)):
            raise PermissionError('Duplicate/uncertain operation')
        order=LimitOrder(plan['side'],1,limit,account=ACCOUNT,orderRef=ref,orderId=order_id,
            tif='DAY',outsideRth=True,transmit=True)
        # Persist intent before transport; every callback is independently timestamped.
        def status(t):
            if t.order.orderRef==ref:journal.event(ref,'ORDER_STATUS',dict(status=t.orderStatus.status,filled=t.orderStatus.filled,remaining=t.orderStatus.remaining,perm_id=t.orderStatus.permId,order_id=t.order.orderId))
        def execution(t,fill):
            if t.order.orderRef==ref:journal.event(ref,'EXECUTION',dict(exec_id=fill.execution.execId,broker_time=str(fill.execution.time),shares=str(fill.execution.shares),price=fill.execution.price,perm_id=fill.execution.permId))
        ib.orderStatusEvent+=status;ib.execDetailsEvent+=execution
        times['send_called_at']=stamp();journal.event(ref,'SEND_CALLED',dict(order_id=order_id,at=times['send_called_at']))
        check_session(details[0].tradingHours,details[0].timeZoneId)
        check_order(stage,bid=ticker.bid,ask=ticker.ask,bid_at=quote_times['bid'],ask_at=quote_times['ask'],
            data_type=ticker.marketDataType,limit=limit,min_tick=float(tick),position=position,baseline=0,
            usd_cash=cash,available_funds=funds,orders=orders,now=time.time(),funding_capacity_usd=funding['capacity_usd'])
        trade=ib.placeOrder(contract,order);report['orders_sent']=1
        acknowledged=await wait_until(lambda:trade.orderStatus.status in ('Filled','Cancelled','ApiCancelled','Inactive') or
            (trade.orderStatus.status in ('PreSubmitted','Submitted') and trade.orderStatus.permId>0),20)
        times['ack_observed_at']=stamp()
        if stage=='cancel' and acknowledged and trade.orderStatus.status in ('PreSubmitted','Submitted'):
            if not owned_order(trade.order,trade.contract,ref,order_id):raise PermissionError('Cancellation ownership mismatch')
            times['cancel_called_at']=stamp();journal.event(ref,'CANCEL_CALLED',dict(order_id=order_id,at=times['cancel_called_at']))
            ib.cancelOrder(trade.order)
            await wait_until(lambda:trade.orderStatus.status in ('Cancelled','ApiCancelled','Filled','Inactive'),20)
        elif stage!='cancel':
            await wait_until(lambda:trade.orderStatus.status in ('Filled','Cancelled','ApiCancelled','Inactive'),40)
            # A known resting test order is safely cancelled once; no price chasing/replay.
            if trade.orderStatus.status in ('Submitted','PreSubmitted') and owned_order(trade.order,trade.contract,ref,order_id):
                times['cancel_called_at']=stamp();journal.event(ref,'CANCEL_CALLED',dict(order_id=order_id))
                ib.cancelOrder(trade.order);await wait_until(lambda:trade.orderStatus.status in ('Cancelled','ApiCancelled','Filled','Inactive'),20)
        final_positions=await asyncio.wait_for(ib.reqPositionsAsync(),8)
        final_orders=await asyncio.wait_for(ib.reqAllOpenOrdersAsync(),8)
        final_execs=await asyncio.wait_for(ib.reqExecutionsAsync(ExecutionFilter(acctCode=ACCOUNT)),8)
        fills=[f for f in final_execs if f.execution.orderRef==ref and f.execution.acctNumber==ACCOUNT and f.execution.orderId==order_id]
        final_position=sum(float(p.position) for p in final_positions if p.account==ACCOUNT and p.contract.conId==contract.conId)
        native=trade.orderStatus.status
        own_open=[t for t in final_orders if t.order.orderRef==ref]
        filled=sum(float(f.execution.shares) for f in {f.execution.execId:f for f in fills}.values())
        outcome=reconciled_outcome(native,filled=filled,open_count=len(own_open),before=position,after=final_position,side=plan['side'],
            rejected=any(e['request_id']==order_id and e['code'] in (201,203,321,10015,10268) for e in errors))
        report.update(status=outcome,native_status=native,final_position=final_position,exec_ids=[f.execution.execId for f in fills],
            fills=[dict(exec_id=f.execution.execId,price=f.execution.price,shares=str(f.execution.shares),broker_time=str(f.execution.time)) for f in fills],
            perm_id=trade.orderStatus.permId,times=times,completed_at=stamp(),errors=errors,
            final_orders=[dict(symbol=t.contract.symbol,perm_id=t.order.permId,order_ref=t.order.orderRef,status=t.orderStatus.status) for t in final_orders])
        journal.finish(ref,outcome,report)
        coordinator.finish_operation('order:'+ref,'UNKNOWN' if outcome=='UNKNOWN' else 'CONFIRMED')
        (evidence/(stage+'.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    except BaseException as exc:
        if ref:
            journal.finish(ref,'UNKNOWN',dict(error_type=type(exc).__name__,error=str(exc),errors=errors,times=times))
            coordinator.finish_operation('order:'+ref,'UNKNOWN')
        raise
    finally:
        if subscribed:ib.cancelMktData(contract)
        ib.disconnect()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('preflight','cancel','fill','close'));args=parser.parse_args()
    os.umask(0o077)
    with monitoring_service('paper-acceptance',STATE_ROOT):asyncio.run(run(args.stage))


if __name__=='__main__':main()
