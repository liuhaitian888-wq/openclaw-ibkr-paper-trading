import hashlib,json,tempfile,unittest
from pathlib import Path
from reporting.secretary_research_evidence import read,freshness
from reporting.secretary_read import tool

class ResearchEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def save(self,name,data):
        rel={'strategy':'reports/paper_strategy/latest.json','news':'runtime/news.latest.json'}[name]
        p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data));return p
    def test_missing_and_injected_path_never_create_or_read_other_files(self):
        self.assertEqual(tool(self.root,{'name':'strategy_evidence'})['state'],'NOT_CREATED')
        self.assertEqual(list(self.root.iterdir()),[])
        with self.assertRaises(ValueError):read(self.root,{'name':'news_evidence','path':'production.json'})
        (self.root/'runtime').symlink_to('/tmp')
        with self.assertRaises(ValueError):read(self.root,{'name':'news_evidence'})
    def test_strategy_uses_per_symbol_time_and_keeps_missing_config_and_gates(self):
        self.save('strategy',{'mode':'MONITOR_ONLY','transmit':False,'symbols':{'ABC':{'observed_at':'1970-01-01T00:00:00+00:00','status':'BLOCKED','reason':'Live bid/ask unavailable','eligible_to_submit':False,'remaining_gates':['Formal execution approval']}},'catalog':{'strategy_states':{'s':{'state':'CONFIG_MISSING'}},'execution_enabled':False}})
        x=read(self.root,{'name':'strategy_evidence'},now=1000)
        self.assertEqual(x['symbols'][0]['freshness'],'STALE');self.assertEqual(x['symbols'][0]['age_seconds'],1000)
        self.assertFalse(x['symbols'][0]['eligible_to_submit']);self.assertEqual(x['catalog']['strategy_states']['s']['state'],'CONFIG_MISSING')
        self.assertEqual(x['catalog_freshness'],'UNKNOWN');self.assertFalse(x['collection_triggered'])
        for value in ['1970-01-01T00:20:00+00:00','1970-01-01T00:00:00','invalid',None]:
            self.assertEqual(freshness(value,1000)['freshness'],'UNKNOWN')
    def test_news_hash_is_not_body_and_failed_retrieval_is_not_success(self):
        data={'source_kind':'BROKER_API','identity_verified':True,'status':'REQUEST_TIMEOUT','news_usable':False,'completed_at':'1970-01-01T00:16:00+00:00','providers':[]}
        self.save('news',data);x=read(self.root,{'name':'news_evidence'},now=1000)
        self.assertEqual(x['freshness'],'FRESH');self.assertFalse(x['news_usable']);self.assertEqual(x['status'],'REQUEST_TIMEOUT')
        provider={'code':'B','article_id':'a','article_sha256':hashlib.sha256(b'body').hexdigest(),'headlines':[{'article_id':'a','provider_code':'B','headline':'headline','time':'old publication','retrieved_at':'retrieved'}]}
        data['providers']=[provider];self.save('news',data)
        self.assertFalse(read(self.root,{'name':'news_evidence'},now=1000)['providers'][0]['articles'][0]['body_available'])
        provider.update(article_text='body',article_text_sha256=hashlib.sha256(b'body').hexdigest(),article_body_complete=True,article_provider_code='B',article_retrieved_at='1970-01-01T00:16:00+00:00');self.save('news',data)
        item=read(self.root,{'name':'news_evidence'},now=1000)['providers'][0]['articles'][0]
        self.assertEqual(item['article_text'],'body');self.assertEqual(item['time'],'old publication')
        provider['article_text']='changed';self.save('news',data)
        self.assertFalse(read(self.root,{'name':'news_evidence'},now=1000)['providers'][0]['articles'][0]['body_available'])
    def test_invalid_size_limits_and_secret_fields(self):
        p=self.save('news',[]);self.assertEqual(read(self.root,{'name':'news_evidence'})['state'],'INVALID_EVIDENCE')
        p.write_bytes(b'x'*512001);self.assertEqual(read(self.root,{'name':'news_evidence'})['state'],'EVIDENCE_TOO_LARGE')
        self.save('strategy',{'symbols':{str(n):{'strategy_configuration':{'password':'fixture-private-value'}} for n in range(30)}})
        x=read(self.root,{'name':'strategy_evidence'},now=1000)
        self.assertEqual(len(x['symbols']),20);self.assertTrue(x['truncated']);self.assertNotIn('fixture-private-value',str(x))
    def test_strategy_parameter_versions_manifest_provenance_and_no_ready_inference(self):
        cfg={'fast_window':3,'slow_window':5}
        self.save('strategy',{'symbols':{'ABC':{'observed_at':'1970-01-01T00:16:00+00:00','strategy_configuration':cfg}}})
        manifest=self.root/'production.json';manifest.write_text(json.dumps({'strategy_configuration':{**cfg,'approved':True},'commit':'example-revision','ready':False,'password':'private-marker'}))
        r=read(self.root,{'name':'strategy_evidence'},now=1000);v=r['symbols'][0]['configuration_provenance']
        self.assertEqual(v['state'],'MATCHING_DECLARED_PARAMETERS');self.assertFalse(r['declared_deployment']['production']['ready']);self.assertNotIn('private-marker',str(r))
        version=v['report_parameters_sha256'];cfg['slow_window']=7
        manifest.write_text(json.dumps({'strategy_configuration':cfg}))
        r=read(self.root,{'name':'strategy_evidence'},now=1000)
        self.assertEqual(r['symbols'][0]['configuration_provenance']['state'],'PARAMETER_MISMATCH');self.assertEqual(r['symbols'][0]['configuration_provenance']['report_parameters_sha256'],version)
        manifest.write_text(json.dumps({'strategy_configuration':{'fast_window':3}}))
        self.assertEqual(read(self.root,{'name':'strategy_evidence'},now=1000)['symbols'][0]['configuration_provenance']['state'],'COMPARISON_INCOMPLETE')
        manifest.write_text('broken')
        self.assertEqual(read(self.root,{'name':'strategy_evidence'},now=1000)['declared_deployment']['production']['state'],'INVALID_EVIDENCE')
