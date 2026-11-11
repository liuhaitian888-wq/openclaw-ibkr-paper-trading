import asyncio,hashlib,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from trading.news_article_evidence import retain,MAX_ARTICLE_BYTES
from trading.news_feed import collect
from reporting.secretary_research_evidence import read
from tests.test_news_feed import FakeIB

class NewsArticleEvidenceTests(unittest.TestCase):
    def test_bounded_unicode_body_content_key_dedup_and_occurrence(self):
        now=datetime.now(timezone.utc);text='正文'*10000
        a=retain(text,provider='REAL',article_id='a',article_type=0,retrieved_at=now,published_at=now)
        b=retain(text,provider='REAL',article_id='a',article_type=0,retrieved_at=now+timedelta(seconds=2),published_at=now)
        self.assertLessEqual(len(a['article_text'].encode()),MAX_ARTICLE_BYTES);self.assertFalse(a['article_body_complete'])
        self.assertEqual(a['article_text_sha256'],hashlib.sha256(a['article_text'].encode()).hexdigest())
        self.assertEqual(a['article_content_key'],b['article_content_key']);self.assertNotEqual(a['article_retrieved_at'],b['article_retrieved_at'])
        c=retain(text+'修订',provider='REAL',article_id='a',article_type=0,retrieved_at=now,published_at=now)
        self.assertNotEqual(a['article_content_key'],c['article_content_key'])
        self.assertEqual(a['article_identity_key'],c['article_identity_key'])
        self.assertNotEqual(a['article_revision_id'],c['article_revision_id'])
        self.assertEqual(a['article_revision_id'],b['article_revision_id'])
        self.assertNotEqual(a['article_occurrence_key'],b['article_occurrence_key'])
        self.assertIsNone(a['article_revision_at'])
        self.assertNotIn('article_text',retain(text,provider='REAL',article_id='a',article_type=1,retrieved_at=now,published_at=now))
    def test_existing_collector_to_reader_body_provenance_expiry_and_tampering(self):
        now=datetime.now(timezone.utc);row=NS(time=now.strftime('%Y-%m-%d %H:%M:%S'),providerCode='REAL',articleId='a',headline='Real title')
        ib=FakeIB(rows=[row])
        with patch.dict('sys.modules',ib_async=NS(StartupFetchNONE=0)):
            result=asyncio.run(collect(ib,lambda *a:None,expected_account='DU123'))
        self.assertEqual(ib.article_calls,1);self.assertTrue(ib.closed)
        p=result['providers'][0];self.assertEqual(p['article_text'],'Actual article body');self.assertTrue(p['article_untrusted_evidence'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'runtime/news.latest.json';path.parent.mkdir();path.write_text(json.dumps(result))
            def article(at):return read(root,{'name':'news_evidence'},now=at)['providers'][0]['articles'][0]
            self.assertTrue(article(now.timestamp()+1)['body_available']);self.assertEqual(article(now.timestamp()+1)['article_text'],'Actual article body')
            self.assertFalse(article(now.timestamp()+302)['body_available']);self.assertNotIn('article_text',article(now.timestamp()+302))
            p['article_text']='tampered';path.write_text(json.dumps(result));self.assertFalse(article(now.timestamp()+1)['body_available'])
            p['article_text']='Actual article body';p['article_provider_code']='OTHER';path.write_text(json.dumps(result));self.assertFalse(article(now.timestamp()+1)['body_available'])
    def test_foreign_provider_headline_does_not_fetch_body(self):
        row=NS(time=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),providerCode='FOREIGN',articleId='a',headline='Foreign')
        ib=FakeIB(rows=[row])
        with patch.dict('sys.modules',ib_async=NS(StartupFetchNONE=0)):
            result=asyncio.run(collect(ib,lambda *a:None,expected_account='DU123'))
        self.assertEqual(ib.article_calls,0);self.assertFalse(result['news_usable'])

    def test_many_real_sized_bodies_stay_bounded_without_erasing_all_evidence(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runtime').mkdir()
            providers=[]
            for i in range(10):
                code='P'+str(i);article='a'+str(i)
                providers.append({'code':code,**retain('long body '*3000,provider=code,article_id=article,article_type=0,retrieved_at=now,published_at=now),
                    'headlines':[{'article_id':article,'provider_code':code,'headline':'reported result','time':now.isoformat()}]})
            (root/'runtime/news.latest.json').write_text(json.dumps({'source_kind':'BROKER_API','identity_verified':True,'completed_at':now.isoformat(),'providers':providers}))
            result=read(root,{'name':'news_evidence'},now=now.timestamp())
            self.assertEqual('BODY_EVIDENCE_AVAILABLE',result['research_evidence_state'])
            self.assertLessEqual(sum(len(a.get('article_text','')) for p in result['providers'] for a in p['articles']),12000)
            self.assertLess(len(json.dumps(result)),45000)
            self.assertTrue(any(a.get('body_budget_limited') for p in result['providers'] for a in p['articles']))
