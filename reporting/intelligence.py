"""Evidence-first intelligence intake. No trading transport or model-native tools."""
from contextlib import closing
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler
import xml.etree.ElementTree as ET
from .agent_secretary import SecretaryArchive
from .incidents import IncidentStore
from .secretary_queue import CONVERSATION

AUTH='intelligence:standing-authority:20261107'
FEEDS={'FED_MONETARY':'https://www.federalreserve.gov/feeds/press_monetary.xml',
       'BLS_CPI':'https://www.bls.gov/feed/cpi.rss','BLS_EMPLOYMENT':'https://www.bls.gov/feed/empsit.rss'}


def publication(value):
    try:
        try:d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except ValueError:d=parsedate_to_datetime(value)
        return d.astimezone(timezone.utc).timestamp() if d.tzinfo else None
    except (ValueError,TypeError,OverflowError,AttributeError):return None


class SourceBackoff(RuntimeError):
    def __init__(self,next_retry,code):
        super().__init__('Source read is in persisted backoff');self.next_retry=next_retry;self.code=code


def fetch(url,*,sec_email=None,retry_state=None):
    host=urlsplit(url).hostname
    if host not in ('www.federalreserve.gov','www.bls.gov','www.sec.gov','data.sec.gov','api.bls.gov'):
        raise PermissionError('Official data host required')
    key=hashlib.sha256(url.encode()).hexdigest();now=time.time()
    prior=(retry_state or {}).get(key,{})
    if prior.get('next_retry',0)>now:raise SourceBackoff(prior['next_retry'],prior.get('http_status'))
    ua='OpenClawReadOnlyResearch'
    if host in ('www.sec.gov','data.sec.gov'):
        if not isinstance(sec_email,str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',sec_email):raise ValueError('SEC contact required')
        ua+=' '+sec_email
    class SameHost(HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if urlsplit(newurl).hostname!=host or urlsplit(newurl).scheme!='https':
                if fp is not None:fp.close()
                raise PermissionError('Cross-host redirect refused before transmission')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    opener=build_opener(SameHost())
    try:
        with opener.open(Request(url,headers={'User-Agent':ua,'Accept':'application/json,application/rss+xml,text/xml'}),timeout=8) as response:
            if urlsplit(response.url).hostname!=host:raise PermissionError('Cross-host redirect refused')
            body=response.read(2_000_001)
    except HTTPError as exc:
        code=exc.code;headers=exc.headers or {};exc.close()
        delay=3600 if code==403 else 600 if code==429 else 120
        retry_after=headers.get('Retry-After')
        if retry_after:
            try:delay=max(delay,min(86400,int(retry_after)))
            except ValueError:
                when=publication(retry_after)
                if when is not None:delay=max(delay,min(86400,max(0,when-now)))
        if retry_state is not None:retry_state[key]={'next_retry':now+delay,'http_status':code}
        raise
    except (OSError,TimeoutError):
        if retry_state is not None:retry_state[key]={'next_retry':now+120,'http_status':None}
        raise
    if retry_state is not None:retry_state.pop(key,None)
    if len(body)>2_000_000:raise ValueError('Response exceeds intake budget')
    return body


def rss_records(body,source):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('DTD refused')
    xml=ET.fromstring(body);result=[]
    for item in xml.findall('.//item')[:30]:
        title=' '.join((item.findtext('title') or '').split())[:400]
        url=item.findtext('link') or ''
        if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in ('www.federalreserve.gov','www.bls.gov','bls.gov'):continue
        result.append({'source':source,'entity':item.findtext('guid') or url,'headline':title,
                       'url':url,'published_at':publication(item.findtext('pubDate')),'category':'macro','symbols':[]})
    return result


def sec_records(body,symbol,cik):
    data=json.loads(body);recent=data.get('filings',{}).get('recent',{});result=[]
    # Array indices are one filing occurrence; missing fields never invent numbers.
    for i,form in enumerate(recent.get('form',[])[:100]):
        if form not in ('8-K','8-K/A','10-Q','10-Q/A','10-K','10-K/A','4','4/A','6-K','20-F'):continue
        def at(name):
            values=recent.get(name,[]);return values[i] if i<len(values) else None
        accession=at('accessionNumber');document=at('primaryDocument')
        if not isinstance(accession,str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession):continue
        if not isinstance(document,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',document):continue
        result.append({'source':'SEC_EDGAR','entity':accession,'headline':symbol+' '+form+' '+str(at('items') or ''),
            'url':'https://www.sec.gov/Archives/edgar/data/'+str(int(cik))+'/'+accession.replace('-','')+'/'+document,
            'published_at':publication(at('acceptanceDateTime')),'filing_date':at('filingDate'),'category':'filing',
            'symbols':[symbol],'form':form,'earnings_relevance':'RESULTS_POSSIBLE' if form.startswith(('10-Q','10-K')) or '2.02' in str(at('items')) else 'NOT_ESTABLISHED',
            'revenue_eps_guidance':'NOT_EXTRACTED; filing alert is not consensus/calendar or financial-value verification'})
    return result


def paper_state(root):
    try:
        with closing(sqlite3.connect((Path(root)/'runtime/recovery.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.1)) as c:
            c.execute('PRAGMA query_only=ON');row=c.execute('SELECT payload FROM paper_safety_state WHERE id=1').fetchone()
        state=json.loads(row[0]) if row else {}
        if not isinstance(state,dict):return {}
        if not (state.get('identity') is True and state.get('connected') is True and not state.get('dirty',True)
                and {'positions','orders','completed_orders','executions'}==set(state.get('ends',[]))
                and 0<=time.time()-state.get('last_server_reply',0)<=60):return {}
        return state
    except (OSError,sqlite3.Error,ValueError):return {}


def held_symbols(state):
    result=[]
    for symbol,qty in state.get('positions',{}).items():
        try:held=math.isfinite(float(qty)) and float(qty)!=0
        except (ValueError,TypeError):held=False
        if held and re.fullmatch(r'[A-Z][A-Z0-9.-]{0,7}',symbol):result.append(symbol)
    return sorted(result)[:12]


def enqueue(store,key,text,*,public_filing=None):
    with closing(store.connect()) as c,c:
        c.execute("INSERT OR IGNORE INTO notification_outbox(incident_key,generation,kind,payload,status) VALUES (?,1,'SECRETARY_REPLY',?,'PENDING')",(key,json.dumps({'reason':text[:3300],'delivery_transport':'telegram','message_role':'INTELLIGENCE', 'public_filing':public_filing},ensure_ascii=False)))


def ingest(archive,store,record,*,now,armed_at):
    normalized={k:v for k,v in record.items() if k not in ('retrieved_at','observed_at')}
    fingerprint=hashlib.sha256(json.dumps(normalized,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    occurrence='intel:'+hashlib.sha256((record['source']+':'+record['entity']).encode()).hexdigest()[:24]+':'+fingerprint[:20]
    with closing(archive.connect()) as c:
        prior=c.execute('SELECT payload FROM secretary_events WHERE occurrence=?',(occurrence,)).fetchone()
    if prior:payload=json.loads(prior[0]);created=False
    else:
        published=record.get('published_at')
        alert=(type(published) in (int,float) and armed_at<=published<=now and now-published<=1800)
        payload={**record,'retrieved_at':now,'content_sha256':fingerprint,'alert_eligible':alert,
                 'verification':'SOURCE_RECORD_VERIFIED','causality':'NOT_ESTABLISHED','trading_permission':False}
        created=archive.append(occurrence,CONVERSATION,origin='TOOL',kind='INTELLIGENCE_RECORD',parent=AUTH,payload=payload)
    if payload['alert_eligible']:
        when=datetime.fromtimestamp(payload['published_at'],timezone.utc).isoformat()
        text='情报事实｜'+payload['source']+'\n'+payload['headline']+'\n发布时间UTC：'+when+'\n'+payload['url']
        if payload.get('symbols'):text+='\n关联标的：'+','.join(payload['symbols'])+'；关联不证明价格变化的因果。'
        text+='\n事实来自列示来源；原因、影响方向、EPS/指引和交易许可未由此确认。'
        if payload.get('provider_article_id'):text+='\n原始provider新闻ID：'+payload['provider_article_id']
        notification_key=occurrence
        if payload['source'].startswith('IBKR_NEWS:'):
            notification_key='intel-news:'+hashlib.sha256(json.dumps([payload['source'],payload['entity'],payload['published_at'],payload['headline']],ensure_ascii=False).encode()).hexdigest()
        enqueue(store,notification_key,text,public_filing={k:payload.get(k) for k in ('source','entity','url','form','symbols','published_at')} if payload.get('source')=='SEC_EDGAR' else None)
    return created


def initialize(archive):
    archive.append(AUTH,CONVERSATION,origin='USER',kind='STANDING_AUTHORIZATION',payload={'source':'User request 2026-11-07, scope summary not third-party claims','text':'建立新闻/财报/宏观/行情异动/持仓风险情报系统，交叉验证并Telegram提醒；优先既有和免费来源，不因此授权交易。'})


def source_result(source,fn):
    try:return {'source':source,'state':'RETRIEVED','records':fn()}
    except Exception as exc:return {'source':source,'state':'WAITING_RETRY' if isinstance(exc,SourceBackoff) else 'UNAVAILABLE','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None),'next_retry':getattr(exc,'next_retry',None),'records':[]}


def public_sources(root,config,*,fetcher=fetch):
    original_fetcher=fetcher
    def fetcher(url,**kwargs):
        if urlsplit(url).hostname in ('www.sec.gov','data.sec.gov'):time.sleep(.15)
        if original_fetcher is fetch:kwargs['retry_state']=config.get('_retry_state')
        return original_fetcher(url,**kwargs)
    feeds=dict(FEEDS)
    if config.get('fed_all_releases') is True:
        feeds.pop('FED_MONETARY');feeds['FED_ALL']='https://www.federalreserve.gov/feeds/press_all.xml'
    results=[source_result(source,lambda source=source,url=url:rss_records(fetcher(url),source)) for source,url in feeds.items()]
    if config.get('macro_api_fallback') is True:
        cache=config.setdefault('_macro_cache',{})
        for source,series in (('BLS_CPI','CUUR0000SA0'),('BLS_EMPLOYMENT','CES0000000001')):
            if any(x['source']==source and x['state']=='RETRIEVED' for x in results):continue
            results.append(bls_snapshot(series,fetcher=fetcher,cache=cache))
    from .research_universe import effective_symbols
    symbols=effective_symbols(root,config,paper_state(root))
    try:
        mapping=json.loads(fetcher('https://www.sec.gov/files/company_tickers.json',sec_email=config.get('sec_contact_email')))
        ciks={v['ticker']:v['cik_str'] for v in mapping.values()}
    except Exception as exc:
        results.append({'source':'SEC_EDGAR','state':'WAITING_RETRY' if isinstance(exc,SourceBackoff) else 'UNAVAILABLE','error_type':type(exc).__name__,'http_status':getattr(exc,'code',None),'next_retry':getattr(exc,'next_retry',None),'records':[]});return results
    for symbol in symbols:
        if symbol not in ciks:
            results.append({'source':'SEC_EDGAR:'+symbol,'state':'CIK_NOT_RESOLVED','records':[]});continue
        cik=ciks[symbol]
        results.append(source_result('SEC_EDGAR:'+symbol,lambda symbol=symbol,cik=cik:sec_records(fetcher('https://data.sec.gov/submissions/CIK'+str(cik).zfill(10)+'.json',sec_email=config.get('sec_contact_email')),symbol,cik)))
    return results


def market_observations(state,previous,*,now,threshold=.02):
    """Only already-owned fresh quotes. No new subscription, daily return or volume claim."""
    baseline={};records=[]
    for symbol,q in state.get('quotes',{}).items():
        try:
            bid,ask=float(q['bid']),float(q['ask']);seen=min(float(q['bid_at']),float(q['ask_at']))
            if q.get('data_type')!=1 or not all(math.isfinite(v) for v in (bid,ask,seen)) or not 0<bid<=ask or not 0<=now-seen<=5:continue
        except (KeyError,ValueError,TypeError):continue
        mid=(bid+ask)/2;old=previous.get(symbol);baseline[symbol]={'mid':mid,'seen':seen,'epoch':state.get('epoch')}
        if not old or old.get('epoch')!=state.get('epoch') or not 0<seen-old.get('seen',seen)<=1200:continue
        try:change=mid/old['mid']-1
        except (ZeroDivisionError,KeyError,TypeError):continue
        if abs(change)>=threshold:
            records.append({'source':'EXISTING_PAPER_QUOTES','entity':str(state.get('epoch'))+':'+symbol+':'+str(seen),
                'headline':symbol+' 现有报价两次采样中点变化 '+format(change*100,'.2f')+'%（非日涨跌幅）',
                'url':'https://www.interactivebrokers.com/','published_at':seen,'category':'market_anomaly','symbols':[symbol],
                'previous_mid':old['mid'],'current_mid':mid,'sample_interval_seconds':seen-old['seen'],
                'timestamp_scope':'local callback receipt, not exchange event time','volume_verified':False,'causal_attribution':'NOT_ESTABLISHED'})
    return records,baseline


def broker_records(result):
    if result.get('source_kind')!='BROKER_API' or result.get('identity_verified') is not True or result.get('expected_account')!='DUQ503649':return []
    records=[]
    for provider in result.get('providers',[]):
        for row in provider.get('headlines',[]):
            body_verified=provider.get('article_id')==row['article_id'] and bool(provider.get('article_sha256'))
            records.append({'source':'IBKR_NEWS:'+provider['code'],'entity':row['article_id'],
                'headline':row['headline'][:400],'published_at':publication(row['time']),
                'url':'https://www.interactivebrokers.com/','provider_article_id':row['article_id'],
                'article_sha256':provider.get('article_sha256') if body_verified else None,
                'article_body_verified':body_verified,'category':'news','symbols':[result['symbol']],
                'scope':'Broker conId query association, not causal proof; scoped historical retrieval, not full-feed streaming'})
    return records


BLS_SERIES={'CUUR0000SA0':('CPI-U all items, US city average, not seasonally adjusted','index 1982-84=100'),
            'CES0000000001':('Total nonfarm payroll employment, seasonally adjusted','thousands of persons')}


def bls_records(body,series):
    if series not in BLS_SERIES:raise ValueError('Fixed official macro series required')
    data=json.loads(body)
    if data.get('status')!='REQUEST_SUCCEEDED':raise ValueError('BLS did not confirm successful query')
    matches=[x for x in data.get('Results',{}).get('series',[]) if x.get('seriesID')==series]
    if len(matches)!=1:raise ValueError('Exact BLS series identity required')
    result=[]
    for row in matches[0].get('data',[])[:36]:
        year,period=str(row.get('year','')),str(row.get('period',''))
        if not re.fullmatch(r'20[0-9]{2}',year) or not re.fullmatch(r'M(0[1-9]|1[0-2])',period):continue
        from decimal import Decimal
        value=None if row.get('value')=='-' else Decimal(str(row.get('value')))
        if value is not None and not value.is_finite():raise ValueError('Finite macro observation required')
        description,unit=BLS_SERIES[series]
        result.append({'source':'BLS_API','entity':series+':'+year+':'+period,'headline':description+' '+year+'-'+period+' = '+('UNAVAILABLE' if value is None else str(value)),
            'url':'https://api.bls.gov/publicAPI/v1/timeseries/data/'+series,'published_at':None,'category':'macro_snapshot','symbols':[],
            'series_id':series,'observation_year':year,'observation_period':period,'value':None if value is None else str(value),'unit':unit,'observation_status':'UNAVAILABLE' if value is None else 'OBSERVED',
            'footnotes':row.get('footnotes',[]),'release_timestamp_verified':False,
            'scope':'Period observation retrieved now, not release-time news or consensus surprise; revisions preserved by content fingerprint'})
    if not result:raise ValueError('No valid monthly observations')
    return result


def bls_snapshot(series,*,fetcher,cache,now=None):
    now=time.time() if now is None else now
    if series not in BLS_SERIES:raise ValueError('Fixed official macro series required')
    previous=cache.get(series,{})
    if previous.get('next_poll',0)>now:
        return {'source':'BLS_API:'+series,'state':'CACHED_SNAPSHOT' if previous.get('records') else 'WAITING_RETRY',
                'observed_at':previous.get('observed_at'),'next_retry':previous['next_poll'],'records':previous.get('records',[])}
    # Two series x four attempts/day = eight calls, under the 25/day unregistered limit.
    cache[series]={'next_poll':now+21600,'observed_at':None,'records':[]}
    result=source_result('BLS_API:'+series,lambda:bls_records(fetcher('https://api.bls.gov/publicAPI/v1/timeseries/data/'+series),series))
    if result['state']=='RETRIEVED':cache[series].update(observed_at=now,records=result['records'])
    result.update(observed_at=cache[series]['observed_at'],next_retry=cache[series]['next_poll'],release_alerts_verified=False)
    return result
