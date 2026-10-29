from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from ibapi.decoder import Decoder
from trading.paper_safety_monitor import PaperSafetyMonitor
from trading.paper_safety_client import PaperSafetyClient
from trading.paper_strategy_observer import PaperStrategyObserver


class BarProtocolTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.m=PaperSafetyMonitor(self.root/'a.db',self.root/'r.db',symbols=['BAC'],required_bars=1,clock=lambda:1200)
  self.c=PaperSafetyClient(self.m,['BAC']);self.c.strategy_observer=PaperStrategyObserver(['BAC'],dict(fast_window=2,slow_window=3),self.root/'o.json')
  self.decoder=Decoder(self.c,220)
 def test_installed_sdk_protobuf_history_update_reaches_existing_observer_once(self):
  from ibapi.decoder import HistoricalDataUpdateProto
  message=HistoricalDataUpdateProto();message.reqId=49000
  b=message.historicalDataBar;b.date='1140';b.open=1;b.high=1;b.low=1;b.close=1;b.volume='1'
  self.decoder.processHistoricalDataUpdateMsgProtoBuf(message.SerializeToString())
  rows=self.m.state['bar_callback_diagnostics']
  self.assertEqual(rows['history_update_protobuf:BAC']['count'],1)
  self.assertEqual(rows['history_update_legacy:BAC']['count'],1)
  self.assertIn(1140,self.c.strategy_observer.bars['BAC'])
  self.assertEqual(len(self.c.strategy_observer.bars['BAC']),1)
 def test_protobuf_realtime_payload_reaches_legacy_filter_without_fabricating_complete_minute(self):
  from ibapi.decoder import RealTimeBarTickProto
  message=RealTimeBarTickProto();message.reqId=47000;message.time=1140
  message.open=1;message.high=1;message.low=1;message.close=1;message.volume='1';message.WAP='1';message.count=1
  self.decoder.processRealTimeBarMsgProtoBuf(message.SerializeToString())
  rows=self.m.state['bar_callback_diagnostics']
  self.assertEqual(rows['realtime_bar_protobuf:BAC']['count'],1)
  self.assertEqual(rows['realtime_bar_legacy:BAC']['count'],1)
  self.assertEqual(self.m.state['bars'],{})
 def test_metadata_neither_requests_subscriptions_nor_submits_orders_and_protocol_is_explicit(self):
  with patch.object(self.c,'serverVersion',return_value=220),patch.object(self.c,'useProtoBuf',return_value=True),patch.object(self.c,'placeOrder') as order,patch.object(self.c,'reqMktData') as quotes:
   self.c.nextValidId(100)
   self.assertTrue(self.m.state['api_protocol']['history_protobuf'])
   self.assertEqual(self.m.state['bar_callback_diagnostics'],{})
   order.assert_not_called();quotes.assert_not_called()
