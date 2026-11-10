from contextlib import closing
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting.intelligence import publication,rss_records,sec_records,initialize,ingest,held_symbols,source_result,public_sources
from reporting.incidents import IncidentStore

class IntelligenceTests(unittest.TestCase):
    def test_feed_times_and_untrusted_dtd_links(self):
        body=b'<rss><channel><item><title>Policy decision</title><link>https://www.federalreserve.gov/policy.htm</link><pubDate>Fri, 06 Nov 2026 13:00:00 GMT</pubDate></item></channel></rss>'
        rows=rss_records(body,'FED_MONETARY');self.assertEqual(len(rows),1);self.assertIsNotNone(rows[0]['published_at'])
        self.assertIsNone(publication('unknown'));self.assertIsNone(publication('2026-11-06T13:00:00'))
        with self.assertRaises(ValueError):rss_records(b'<!DOCTYPE a><rss/>','FED')
        self.assertEqual(rss_records(body.replace(b'www.federalreserve.gov',b'evil.invalid'),'FED'),[])
    def test_sec_acceptance_time_source_form_and_no_fake_eps(self):
        body=json.dumps({'filings':{'recent':{'form':['8-K'],'accessionNumber':['0001045810-26-000001'],'primaryDocument':['report.htm'],'acceptanceDateTime':['2026-11-06T13:00:00Z'],'items':['2.02']}}}).encode()
        result=sec_records(body,'NVDA',1045810)[0]
        self.assertEqual(result['earnings_relevance'],'RESULTS_POSSIBLE');self.assertIn('NOT_EXTRACTED',result['revenue_eps_guidance'])
        self.assertIn('000104581026000001/report.htm',result['url'])
        self.assertEqual(sec_records(body.replace(b'report.htm',b'../private'),'NVDA',1045810),[])
    def test_duplicate_and_cold_start_no_spam_but_new_publication_notifies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'secretary.sqlite3');initialize(a);s=IncidentStore(root/'recovery.sqlite3')
            record={'source':'FED','entity':'one','headline':'policy','url':'https://www.federalreserve.gov/policy','published_at':99,'category':'macro','symbols':[]}
            self.assertTrue(ingest(a,s,record,now=110,armed_at=100));self.assertFalse(ingest(a,s,record,now=111,armed_at=100));self.assertIsNone(s.claim())
            record={**record,'entity':'two','published_at':105}
            ingest(a,s,record,now=110,armed_at=100);ingest(a,s,record,now=112,armed_at=100)
            self.assertIsNotNone(s.claim());self.assertIsNone(s.claim())
            with closing(s.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM incidents').fetchone()[0],0)
    def test_revised_content_has_distinct_fingerprint_not_silent_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'a.sqlite3');initialize(a);s=IncidentStore(root/'r.sqlite3')
            row={'source':'SEC','entity':'one','headline':'first','url':'https://www.sec.gov/x','published_at':None,'symbols':[]}
            ingest(a,s,row,now=100,armed_at=100);ingest(a,s,{**row,'headline':'amended'},now=101,armed_at=100)
            self.assertEqual(sum(e['kind']=='INTELLIGENCE_RECORD' for e in a.history('der-secretary')),2)
    def test_errors_are_not_subscription_or_retrieval_success(self):
        def failed():raise TimeoutError()
        result=source_result('BLS',failed);self.assertEqual(result['state'],'UNAVAILABLE');self.assertNotIn('unsubscribed',str(result).lower())
    def test_flat_nan_and_manual_exposure(self):
        self.assertEqual(held_symbols({'positions':{'AAPL':1,'NVDA':0,'PFE':-2,'MSFT':float('nan')}}),['AAPL','PFE'])
    def test_legacy_technical_progress_does_not_emit_user_notifications(self):
        from reporting.secretary_queue import progress
        with tempfile.TemporaryDirectory() as tmp:
            store=IncidentStore(Path(tmp)/'recovery.sqlite3')
            progress(store,'run','CLAIMED','starting');progress(store,'run','CLAIMED','starting')
            self.assertIsNone(store.claim())
    def test_existing_quote_movement_has_window_not_daily_or_causal_claim(self):
        from reporting.intelligence import market_observations
        state={'epoch':'same','quotes':{'AAPL':{'bid':97,'ask':99,'bid_at':100,'ask_at':100,'data_type':1}}}
        records,baseline=market_observations(state,{'AAPL':{'epoch':'same','mid':101,'seen':50}},now=102)
        self.assertEqual(len(records),1);self.assertEqual(records[0]['sample_interval_seconds'],50)
        self.assertFalse(records[0]['volume_verified']);self.assertEqual(records[0]['causal_attribution'],'NOT_ESTABLISHED')
        self.assertEqual(market_observations(state,baseline,now=106)[0],[])
        self.assertEqual(market_observations(state,{'AAPL':{'epoch':'old','mid':101,'seen':50}},now=102)[0],[])
    def test_sec_contact_only_sent_to_sec_and_cross_host_redirect_blocked(self):
        from unittest.mock import MagicMock
        from reporting.intelligence import fetch
        response=MagicMock();response.read.return_value=b'{}';response.url='https://data.sec.gov/submissions/CIK0000000001.json'
        response.__enter__.return_value=response
        with patch('reporting.intelligence.build_opener') as build:
            build.return_value.open.return_value=response
            fetch(response.url,sec_email='fixture@example.invalid')
            request=build.return_value.open.call_args.args[0]
            self.assertIn('fixture@example.invalid',request.get_header('User-agent'))
            handler=build.call_args.args[0]
            with self.assertRaises(PermissionError):handler.redirect_request(None,None,302,'redirect',{},'https://evil.invalid/x')
            response.url='https://www.federalreserve.gov/feeds/press_monetary.xml'
            fetch(response.url,sec_email='fixture@example.invalid')
            request=build.return_value.open.call_args.args[0]
            self.assertNotIn('fixture@example.invalid',request.get_header('User-agent'))
        with self.assertRaises(PermissionError):fetch('https://evil.invalid')
    def test_public_sources_use_official_cik_mapping_and_exact_held_symbol(self):
        rss=b'<rss><channel><item><title>Release</title><link>https://www.bls.gov/release.htm</link><pubDate>Fri, 06 Nov 2026 13:00:00 GMT</pubDate></item></channel></rss>'
        def fetcher(url,**kwargs):
            if url.endswith('company_tickers.json'):return json.dumps({'0':{'ticker':'AAPL','cik_str':320193}}).encode()
            if '/submissions/' in url:
                self.assertTrue(url.endswith('CIK0000320193.json'))
                return json.dumps({'filings':{'recent':{'form':[]}}}).encode()
            return rss
        with patch('reporting.intelligence.paper_state',return_value={'positions':{'AAPL':1,'NVDA':0}}),patch('reporting.intelligence.time.sleep'):
            sources=public_sources(Path('/unused'),{'sec_contact_email':'fixture@example.invalid'},fetcher=fetcher)
        self.assertEqual(len(sources),4);self.assertEqual(sources[-1]['source'],'SEC_EDGAR:AAPL')
        self.assertTrue(all(s['state']=='RETRIEVED' for s in sources))
    def test_broker_body_hash_only_belongs_to_the_article_actually_retrieved(self):
        from reporting.intelligence import broker_records
        result={'source_kind':'BROKER_API','identity_verified':True,'expected_account':'DUQ503649','symbol':'AAPL','providers':[{'code':'DJ','article_id':'new','article_sha256':'verified','headlines':[{'article_id':'new','headline':'new','time':'2026-11-06T13:00:00Z'},{'article_id':'old','headline':'old','time':'2026-11-06T12:00:00Z'}]}]}
        rows=broker_records(result)
        self.assertTrue(rows[0]['article_body_verified']);self.assertFalse(rows[1]['article_body_verified']);self.assertIsNone(rows[1]['article_sha256'])
        self.assertEqual(broker_records({**result,'identity_verified':False}),[])
    def test_same_news_article_across_query_symbols_notifies_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=SecretaryArchive(root/'a.sqlite3');initialize(a);store=IncidentStore(root/'r.sqlite3')
            row={'source':'IBKR_NEWS:DJ','entity':'article','provider_article_id':'article','headline':'one event','url':'https://www.interactivebrokers.com/','published_at':105,'symbols':['AAPL']}
            ingest(a,store,row,now=110,armed_at=100);ingest(a,store,{**row,'symbols':['MSFT']},now=111,armed_at=100)
            self.assertIsNotNone(store.claim());self.assertIsNone(store.claim())
    def test_http_error_response_closes_and_persisted_backoff_prevents_repeat(self):
        import io
        from urllib.error import HTTPError
        from reporting.intelligence import fetch,SourceBackoff
        body=io.BytesIO(b'denied');error=HTTPError('https://www.bls.gov/feed/cpi.rss',403,'denied',{},body);retries={}
        with patch('reporting.intelligence.build_opener') as build,patch('reporting.intelligence.time.time',return_value=100):
            build.return_value.open.side_effect=error
            with self.assertRaises(HTTPError):fetch('https://www.bls.gov/feed/cpi.rss',retry_state=retries)
            self.assertTrue(body.closed)
            with self.assertRaises(SourceBackoff):fetch('https://www.bls.gov/feed/cpi.rss',retry_state=retries)
            self.assertEqual(build.return_value.open.call_count,1)
    def test_bls_api_snapshot_is_not_a_release_alert_and_caches_quota_on_failure(self):
        from reporting.intelligence import bls_records,bls_snapshot
        body=json.dumps({'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'CUUR0000SA0','data':[{'year':'2026','period':'M09','value':'336.940','footnotes':[]}]}]}}).encode()
        rows=bls_records(body,'CUUR0000SA0');self.assertIsNone(rows[0]['published_at']);self.assertFalse(rows[0]['release_timestamp_verified'])
        cache={};calls=[]
        def fetcher(url):calls.append(url);return body
        self.assertEqual(bls_snapshot('CUUR0000SA0',fetcher=fetcher,cache=cache,now=100)['state'],'RETRIEVED')
        self.assertEqual(bls_snapshot('CUUR0000SA0',fetcher=fetcher,cache=cache,now=200)['state'],'CACHED_SNAPSHOT');self.assertEqual(len(calls),1)
        def failure(url):raise TimeoutError()
        cache={};self.assertEqual(bls_snapshot('CES0000000001',fetcher=failure,cache=cache,now=100)['state'],'UNAVAILABLE')
        self.assertEqual(bls_snapshot('CES0000000001',fetcher=fetcher,cache=cache,now=200)['state'],'WAITING_RETRY');self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):bls_records(body,'CES0000000001')
        with self.assertRaises(ValueError):bls_records(body.replace(b'336.940',b'NaN'),'CUUR0000SA0')

    def test_official_unavailable_month_is_retained_as_gap_not_fatal(self):
        from reporting.intelligence import bls_records
        body=json.dumps({'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'CUUR0000SA0','data':[{'year':'2025','period':'M10','value':'-','footnotes':[{'text':'Data unavailable'}]},{'year':'2025','period':'M11','value':'300','footnotes':[]}]}]}}).encode()
        rows=bls_records(body,'CUUR0000SA0');self.assertEqual(len(rows),2);self.assertIsNone(rows[0]['value']);self.assertEqual(rows[0]['observation_status'],'UNAVAILABLE');self.assertEqual(rows[1]['value'],'300')
