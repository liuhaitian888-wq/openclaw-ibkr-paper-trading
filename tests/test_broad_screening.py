from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from types import SimpleNamespace as NS
from reporting import screening_sources as s
from reporting import broad_screening as b
from reporting.agent_secretary import SecretaryArchive
from reporting.security_directory import initialize as directory_init
from trading.broker_screening import BrokerScanner,queue

NOW=datetime(2026,11,9,12,tzinfo=timezone.utc).timestamp()


def market(symbol='AAPL',**changes):
    return dict(dict(symbol=symbol,price=100,volume=2_000_000,average_volume=None,market_cap=1e9,
                     price_date='2026-11-06',price_at=None,time_quality='DATE_ONLY',source='NASDAQ_SCREENER',currency='USD'),**changes)


class SourceTests(unittest.TestCase):
    def test_missing_numbers_are_not_zero_and_nasdaq_date_requires_sample_alignment(self):
        for x in (None,'N/A','--','nan',float('inf'),True):self.assertIsNone(s.number(x))
        self.assertEqual(s.number('0'),0);self.assertEqual(s.number('$1,234.5'),1234.5)
        rows=[dict(symbol=sym,lastsale='$100',volume='1000000',marketCap='N/A') for sym in ('AAPL','MSFT','NVDA')]
        data=json.dumps({'data':{'rows':rows,'totalrecords':3}}).encode()
        meta=json.dumps({'data':{'asof':'Last price as of Nov 6, 2026','table':{'rows':rows}}}).encode()
        result,info=s.nasdaq(data,meta);self.assertEqual(result[0]['price_date'],'2026-11-06');self.assertIsNone(result[0]['market_cap'])
        rows[0]['lastsale']='$99'
        mismatch=json.dumps({'data':{'asof':'Last price as of Nov 6, 2026','table':{'rows':rows}}}).encode()
        result,info=s.nasdaq(data,mismatch);self.assertIsNone(result[0]['price_date']);self.assertFalse(info['date_metadata_price_samples_match'])

    def test_yahoo_top_list_and_average_volume_keep_scope_and_time(self):
        raw=json.dumps({'finance':{'result':[{'total':450,'quotes':[{'symbol':'AAPL','regularMarketPrice':100,'regularMarketVolume':5000,
             'averageDailyVolume3Month':8000,'regularMarketTime':NOW,'currency':'USD'}]}]}}).encode()
        rows,info=s.yahoo(raw);self.assertTrue(info['partial']);self.assertEqual(rows[0]['average_volume_window'],'3_MONTH')
        self.assertEqual(rows[0]['price_at'],NOW);self.assertNotEqual(rows[0]['volume'],rows[0]['average_volume'])

    def test_sec_units_period_and_issuer_identity_are_explicit(self):
        raw=json.dumps({'taxonomy':'us-gaap','tag':'Assets','uom':'USD','ccp':'CY2026Q3I','data':[
            {'cik':1,'val':0,'end':'2026-09-30','accn':'a'}]}).encode()
        facts=s.sec_frame(raw,tag='Assets',unit='USD',period='CY2026Q3I')
        self.assertEqual(facts[1]['value'],0);self.assertIsNone(facts[1]['filed_at']);self.assertFalse(facts[1]['point_in_time_verified'])
        with self.assertRaises(ValueError):s.sec_frame(raw,tag='Assets',unit='EUR',period='CY2026Q3I')
        mapping=s.sec_mapping(json.dumps({'0':{'ticker':'A','cik_str':1},'1':{'ticker':'A','cik_str':2}}).encode());self.assertNotIn('A',mapping)

    def test_http_response_lifecycle_and_persisted_backoff(self):
        from urllib.error import HTTPError
        error=HTTPError(s.NASDAQ,429,'rate',{},None);retry={}
        with patch('reporting.screening_sources.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(HTTPError):s.fetch(s.NASDAQ,retry=retry,now=NOW)
            with self.assertRaises(s.Backoff):s.fetch(s.NASDAQ,retry=retry,now=NOW+1)
            self.assertEqual(opener.return_value.open.call_count,1)
        self.assertGreater(retry[s.NASDAQ]['not_before'],NOW)
        response=MagicMock();response.read.return_value=b'{}'
        with patch('reporting.screening_sources.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=response
            self.assertEqual(s.fetch(s.NASDAQ),b'{}');opener.return_value.open.return_value.__exit__.assert_called_once()
        with self.assertRaises(PermissionError):s.fetch('https://example.com/secret')


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3');directory_init(self.a);b.initialize(self.a)
        with closing(self.a.connect()) as c,c:
            for sym in ('AAPL','MSFT','MISSING'):
                c.execute("INSERT INTO market_security_master VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'PENDING')",
                    ('n:'+sym,sym,sym,'NASDAQ','C','STOCK',sym,'',sym,'N','official','1106202621:31','r',NOW))
    def test_research_layers_never_grant_runtime_or_fill_missing_fundamentals(self):
        b.ingest_market(self.a,'NASDAQ_SCREENER',[market(),market('MSFT',volume=None)],{},'r',NOW)
        result=b.rebuild(self.a,self.root,now=NOW)
        self.assertEqual(result['coarse_candidates'],1)
        with closing(self.a.connect()) as c:
            row=c.execute("SELECT layer,payload FROM screen_pool_projection WHERE symbol='AAPL'").fetchone()
            missing=c.execute("SELECT layer,payload FROM screen_pool_projection WHERE symbol='MISSING'").fetchone()
        self.assertEqual(row[0],'ELIGIBLE_UNIVERSE');payload=json.loads(row[1]);self.assertFalse(payload['canonical_execution_active'])
        self.assertIn('AVERAGE_VOLUME_MISSING',payload['flags']);self.assertIn('REALTIME_PERMISSION_PENDING',payload['runtime_blocks'])
        self.assertEqual(missing[0],'MASTER_UNIVERSE');self.assertIn('PRICE_MISSING',json.loads(missing[1])['flags'])
        self.assertFalse((self.root/'trading_audit.sqlite3').exists())
    def test_only_real_fresh_completed_scanner_crosses_research_layer_three(self):
        b.ingest_market(self.a,'NASDAQ_SCREENER',[market()],{},'r',NOW)
        with closing(self.a.connect()) as c,c:
            c.execute("INSERT INTO broker_screen_requests VALUES('scan','MOST_ACTIVE','SUCCEEDED',?,?,?,?,'conn','{}')",(NOW,NOW+180,NOW,NOW))
            c.execute("INSERT INTO broker_screen_results VALUES('scan',0,'AAPL',123,'NASDAQ','USD','STK',?)",(NOW,))
        self.assertEqual(b.rebuild(self.a,self.root,now=NOW)['scanner_cross_candidates'],1)
        self.assertEqual(b.rebuild(self.a,self.root,now=NOW+3601)['scanner_cross_candidates'],0)
    def test_stale_data_and_default_filters_and_pagination(self):
        b.ingest_market(self.a,'NASDAQ_SCREENER',[market(price_date='2026-10-01')],{},'r',NOW)
        b.rebuild(self.a,self.root,now=NOW)
        page=b.view(self.root,'layer=2',now=NOW);self.assertEqual(page['total'],0)
        row=b.view(self.root,'q=AAPL',now=NOW)['rows'][0];self.assertIn('STALE',row['flags'])
        with self.assertRaises(ValueError):b.view(self.root,'min_price=NaN',now=NOW)
        with self.assertRaises(ValueError):b.view(self.root,'layer=6',now=NOW)
    def test_refresh_request_dedupe_and_schedule_does_not_backfill_old_slots(self):
        a=b.enqueue(self.a,origin='USER',identity='one',now=NOW)
        self.assertEqual(b.enqueue(self.a,origin='USER',identity='two',now=NOW)['id'],a['id'])
        with closing(self.a.connect()) as c,c:c.execute("UPDATE screen_refresh_jobs SET state='UNKNOWN'")
        b.schedule(self.a,NOW) # midday Berlin: no due morning slot
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM screen_refresh_jobs').fetchone()[0],1)
    def test_compare_refuses_date_only_and_accepts_only_aligned_last_trades(self):
        from reporting.screening_comparison import compare
        b.ingest_market(self.a,'NASDAQ_SCREENER',[market()],{},'r',NOW)
        (self.root/'runtime').mkdir()
        native=dict(identity=True,connected=True,upstream_connected=True,last_server_reply=NOW,
                    quotes={'AAPL':dict(last=99,last_at=NOW,event_time=str(NOW-5))},
                    contracts={'AAPL':dict(con_id=123,currency='USD',sec_type='STK',external_symbol='AAPL',external_identity_verified=True)},market_types={'AAPL':1})
        with closing(sqlite3.connect(self.root/'runtime/recovery.sqlite3')) as c,c:
            c.execute('CREATE TABLE paper_safety_state(id INTEGER,payload TEXT)');c.execute('INSERT INTO paper_safety_state VALUES(1,?)',(json.dumps(native),))
        row=compare(self.root,'AAPL',now=NOW)['comparisons'][0]
        self.assertEqual(row['status'],'NOT_DIRECTLY_COMPARABLE');self.assertIsNone(row['difference_pct'])
        b.ingest_market(self.a,'YAHOO_MOST_ACTIVE',[market(price_at=NOW-5,price_date='2026-11-09',source='YAHOO_MOST_ACTIVE')],{},'r',NOW)
        row=next(x for x in compare(self.root,'AAPL',now=NOW)['comparisons'] if x['source']=='YAHOO_MOST_ACTIVE')
        self.assertEqual(row['status'],'TIME_ALIGNED_OBSERVATION');self.assertAlmostEqual(row['difference_pct'],100/99)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.now=NOW;self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3');self.client=MagicMock(connection_generation='connection')
        self.adapter=BrokerScanner(self.client,self.a,clock=lambda:self.now)
    def test_existing_client_only_native_end_and_owned_cancel(self):
        job=queue(self.a,now=self.now,identity='owner:scan');self.adapter.poll(admitted=True)
        self.client.reqScannerSubscription.assert_called_once();self.client.connect.assert_not_called()
        request=self.adapter.active['request']
        self.adapter.data(request,0,NS(contract=NS(symbol='AAPL',conId=123,primaryExchange='NASDAQ',currency='USD',secType='STK')))
        self.adapter.end(request);self.adapter.poll(admitted=True)
        self.client.cancelScannerSubscription.assert_called_once_with(request)
        self.client.reqMktData.assert_not_called();self.client.placeOrder.assert_not_called();self.client.cancelOrder.assert_not_called()
        with closing(self.a.connect()) as c:
            self.assertEqual(c.execute('SELECT state FROM broker_screen_requests').fetchone()[0],'SUCCEEDED')
            self.assertEqual(c.execute('SELECT symbol FROM broker_screen_results').fetchone()[0],'AAPL')
        self.adapter.end(request);self.assertIsNone(self.adapter.active)
    def test_restart_and_timeout_unknown_do_not_replay(self):
        queue(self.a,now=self.now);self.adapter.poll(admitted=True)
        self.now+=21;self.adapter.poll(admitted=True);self.assertIsNone(self.adapter.active)
        other=BrokerScanner(self.client,self.a,clock=lambda:self.now);other.poll(admitted=True)
        self.assertEqual(self.client.reqScannerSubscription.call_count,1)
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT state FROM broker_screen_requests').fetchone()[0],'UNKNOWN')
    def test_closed_dependency_expires_queued_and_close_cancels_owned_request(self):
        queue(self.a,now=self.now);self.adapter.poll(admitted=False);self.client.reqScannerSubscription.assert_not_called()
        self.now+=181;self.adapter.poll(admitted=True)
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT state FROM broker_screen_requests').fetchone()[0],'EXPIRED')
        queue(self.a,now=self.now);self.adapter.poll(admitted=True);self.adapter.close()
        self.client.cancelScannerSubscription.assert_called_once()
    def test_error_is_not_a_success_and_rows_are_bounded(self):
        queue(self.a,now=self.now);self.adapter.poll(admitted=True);request=self.adapter.active['request']
        self.adapter.data(request,99,NS(contract=NS(symbol='X',conId=1)))
        self.assertFalse(self.adapter.active['rows']);self.assertTrue(self.adapter.error(request,354));self.adapter.poll(admitted=True)
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT state FROM broker_screen_requests').fetchone()[0],'FAILED')
    def test_new_protocol_decoder_still_dispatches_native_scanner_end(self):
        from ibapi.decoder import Decoder
        from ibapi.protobuf.ScannerData_pb2 import ScannerData
        from trading.paper_safety_client import PaperSafetyClient
        from trading.paper_safety_monitor import PaperSafetyMonitor
        monitor=PaperSafetyMonitor(self.root/'audit.db',self.root/'recovery.db',symbols=['AAPL'],required_bars=2)
        client=PaperSafetyClient(monitor,['AAPL']);client.research_scanner=MagicMock()
        message=ScannerData();message.reqId=80000
        element=message.scannerDataElement.add();element.rank=0;element.contract.conId=123;element.contract.symbol='AAPL'
        Decoder(client,0).processScannerDataMsgProtoBuf(message.SerializeToString())
        client.research_scanner.data.assert_called_once();client.research_scanner.end.assert_called_once_with(80000)


class TelegramScreenTests(unittest.TestCase):
    def test_native_owner_controls_queue_reads_without_model_or_network(self):
        from reporting.secretary_queue import initialize,accept_update
        from reporting.secretary_controls import process_controls,menu_commands
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent_secretary.sqlite3');initialize(a)
            cfg=dict(owner_user_id=123,owner_private_chat_id=123,owner_private_verified=True,bot_username='fixture')
            for uid,text in enumerate(['/screen','/screen_refresh','/scan','/compare AAPL','/data_status'],1):
                u=dict(update_id=uid,message=dict(chat=dict(id=123,type='private'),date=int(NOW),message_id=uid,text=text,**{'from':dict(id=123,is_bot=False)}))
                self.assertTrue(accept_update(a,u,cfg,armed_at=1))
            with patch('subprocess.run') as shell,patch('urllib.request.urlopen') as network:process_controls(a,root,cfg)
            shell.assert_not_called();network.assert_not_called()
            with closing(a.connect()) as c:
                self.assertEqual(c.execute("SELECT count(*) FROM secretary_runs WHERE model='PYTHON_CONTROL' AND state='SUCCEEDED'").fetchone()[0],5)
                self.assertEqual(c.execute('SELECT count(*) FROM screen_refresh_jobs').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM broker_screen_requests').fetchone()[0],1)
            self.assertTrue({'screen','screen_refresh','scan','compare','data_status'}.issubset({x[0] for x in menu_commands()}))

    def test_optional_screening_modules_do_not_block_system_until_enabled(self):
        from reporting.health import resolve_modules
        result=resolve_modules({})
        self.assertFalse(result['BROAD_SCREENING']['active']);self.assertFalse(result['BROKER_SCANNER']['active'])


class FullRefreshTests(unittest.TestCase):
    def test_sources_partial_financial_gap_preserves_other_fields_and_versions(self):
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'agent_secretary.sqlite3');directory_init(a);b.initialize(a)
            with closing(a.connect()) as c,c:
                c.execute("INSERT INTO market_security_master VALUES('n:AAPL','AAPL','Apple','NASDAQ','C','STOCK','AAPL','','AAPL','N','official','1106202621:31','r',?,1,'PENDING')",(NOW,))
            rows=[dict(symbol=sym,lastsale='$100',volume='2000000',marketCap='10000000') for sym in ['AAPL','MSFT','NVDA']+['T'+str(i) for i in range(497)]]
            def loader(url,**kw):
                if url==s.NASDAQ:return json.dumps({'data':{'rows':rows,'totalrecords':500}}).encode()
                if url==s.NASDAQ_DATE:return json.dumps({'data':{'asof':'Last price as of Nov 6, 2026','table':{'rows':rows}}}).encode()
                if url.startswith(s.YAHOO):return json.dumps({'finance':{'result':[{'total':1,'quotes':[{'symbol':'AAPL','regularMarketPrice':100,'regularMarketVolume':2000000,'regularMarketTime':NOW-10,'currency':'USD'}]}]}}).encode()
                if url==s.SEC_MAPPING:return json.dumps({'0':{'ticker':'AAPL','cik_str':320193}}).encode()
                tag=url.split('/')[-3];period=url.split('/')[-1].removesuffix('.json')
                if tag.startswith('Revenue'):raise HTTPError(url,404,'missing',{},None)
                return json.dumps({'taxonomy':'us-gaap','tag':tag,'uom':'USD','ccp':period,'data':[{'cik':320193,'end':'2026-09-30','val':0,'accn':'filing'}]}).encode()
            with patch('reporting.broad_screening.time.sleep'):
                result=b.refresh(a,root,'fixture-refresh',loader=loader,now=NOW)
            self.assertEqual(result['sources']['SEC_FRAMES'],'AVAILABLE_PARTIAL_RESEARCH')
            with closing(a.connect()) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM screen_fundamentals').fetchone()[0],3)
                self.assertEqual(c.execute("SELECT state FROM screen_source_status WHERE source='SEC_FRAMES'").fetchone()[0],'AVAILABLE_PARTIAL_RESEARCH')
                self.assertGreater(c.execute('SELECT count(*) FROM screen_versions').fetchone()[0],4)
                payload=json.loads(c.execute('SELECT payload FROM screen_pool_projection').fetchone()[0])
            self.assertIn('FUNDAMENTALS_PARTIAL_OR_MISSING',payload['flags']);self.assertEqual(payload['fundamentals']['assets']['value'],0)
            self.assertFalse((root/'trading_audit.sqlite3').exists())


class ScannerOwnerWiringTests(unittest.TestCase):
    def test_policy_attaches_only_to_existing_client_without_connecting(self):
        from ops.cloud.paper_safety_watch import attach_research_scanner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();client=MagicMock();client.research_scanner=None
            self.assertIsNone(attach_research_scanner(client,root))
            policy=dict(approved=True,environment='LIVE',broker_scanner_readonly=True,grants_trading_permission=False)
            path=root/'runtime/screening-policy.json';path.write_text(json.dumps(policy))
            self.assertIsNone(attach_research_scanner(client,root))
            policy['environment']='PAPER';path.write_text(json.dumps(policy))
            adapter=attach_research_scanner(client,root)
            self.assertIs(adapter.client,client);self.assertIs(client.research_scanner,adapter)
            client.connect.assert_not_called();client.reqScannerSubscription.assert_not_called()
            adapter.close()
