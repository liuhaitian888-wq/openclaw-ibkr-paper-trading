import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import patch
import unittest
from ops.cloud.protection_repair import Broker

class NativeProtectionAdapterTests(unittest.TestCase):
 def test_confirmed_requires_exact_native_order_and_position_readback(self):
  p=dict(symbol='AAPL',con_id=123,quantity=17,stop_price='95.00',order_ref='legacy-protection-20261109-v1:AAPL:123')
  native=dict(orders=[dict(order_ref=p['order_ref'],account='DUQ503649',con_id=123,symbol='AAPL',side='SELL',order_type='STP',tif='GTC',transmit=True,perm_id=77,status='PreSubmitted',remaining='17',quantity='17',aux_price=95)],positions=[dict(con_id=123,quantity='17')],observed_at=100,oldest_end_at=100)
  for change in [None,'wrong_contract','partial','extra_sell','stale']:
   with self.subTest(change=change):
    data=deepcopy(native)
    if change=='wrong_contract':data['orders'][0]['con_id']=124
    if change=='partial':data['orders'][0]['remaining']='10'
    if change=='extra_sell':data['orders'].append({**data['orders'][0],'order_ref':'manual'})
    if change=='stale':data['oldest_end_at']=90
    calls=[]
    def place(c,o):
     calls.append((c,o));o.orderId=11;o.permId=77
     return NS(order=o,orderStatus=NS(status='PreSubmitted'))
    b=Broker.__new__(Broker);b.errors=[];b.clock=lambda:100;b.ib=NS(placeOrder=place)
    async def snapshot():return data
    b.snapshot=snapshot
    def stop(action,qty,price,**kwargs):return NS(action=action,totalQuantity=qty,auxPrice=price,**kwargs)
    with patch.dict('sys.modules',{'ib_async':NS(StopOrder=stop,Contract=lambda **kw:NS(**kw))}):
     r=asyncio.run(b.submit_stop(p))
    self.assertEqual(r['status'],'CONFIRMED' if change is None else 'UNKNOWN')
    self.assertEqual(len(calls),1);self.assertEqual(calls[0][1].action,'SELL');self.assertFalse(calls[0][1].outsideRth)
 def test_own_subscription_cancel_failure_still_disconnects_own_client(self):
  calls=[];b=Broker.__new__(Broker);b.subscription=NS(conId=123)
  def cancel(c):calls.append(('cancel_market_data',c.conId));raise RuntimeError('cancel failed')
  b.ib=NS(isConnected=lambda:True,cancelMktData=cancel,disconnect=lambda:calls.append(('disconnect',)))
  with self.assertRaises(RuntimeError):b.close()
  self.assertEqual(calls,[('cancel_market_data',123),('disconnect',)])
