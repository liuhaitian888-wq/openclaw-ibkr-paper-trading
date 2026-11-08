from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from reporting.agent_secretary import SecretaryArchive
from reporting import security_directory as d
from reporting import market_subscriptions as m

NOW=datetime(2026,11,8,12,tzinfo=timezone.utc).timestamp()

def files(n=3,footer='1106202621:31'):
    nq='Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n'
    nq+='\n'.join(f'Q{i:02d}|Example {i} Common Stock|Q|N|N|100|N|N' for i in range(n))+'\n'
    nq+='ZTEST|Test Common Stock|Q|Y|N|100|N|N\nFile Creation Time: '+footer+'|||||||\n'
    other='ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n'
    other+='AAA|Alpha Common Stock|N|AAA|N|100|N|AAA\n'
    other+='ETF|An Example ETF|P|ETF|Y|100|N|ETF\n'
    other+='PREF$A|Preferred shares|A|PREFpA|N|100|N|PREF-A\n'
    other+='UNK|Unknown Common Stock|F|UNK|N|100|N|UNK\nFile Creation Time: '+footer+'||||||\n'
    return {'nasdaqlisted':nq.encode(),'otherlisted':other.encode()}


class SecurityDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.a=SecretaryArchive(self.root/'agent_secretary.sqlite3')
        self.data=files();m.initialize(self.a)
    def refresh(self,**kw):return d.refresh(self.a,self.root,loader=lambda n:self.data[n],now=NOW,minimum=1,**kw)
    def test_network_types_aliases_unknowns_and_permissions_are_distinct(self):
        self.refresh()
        rows=d.view(self.root)['rows'];self.assertEqual(d.view(self.root)['total'],6)
        self.assertEqual({r['network'] for r in rows},{'A','B','C'})
        self.assertTrue(all(r['permission_status']=='PENDING' for r in rows))
        self.assertEqual(d.view(self.root,'network=UNKNOWN')['total'],1)
        self.assertEqual(d.view(self.root,'network=B type=ETF')['rows'][0]['symbol'],'ETF')
        with closing(self.a.connect()) as c:
            self.assertEqual(c.execute("SELECT cqs_symbol,nasdaq_symbol FROM market_security_master WHERE symbol='PREF$A'").fetchone(),('PREFpA','PREF-A'))
            self.assertEqual(c.execute("SELECT count(*) FROM market_security_master WHERE symbol='ZTEST'").fetchone()[0],0)
        self.assertEqual(d.asset_type('Warrants to purchase Common Stock','N'),'OTHER')

    def test_failed_or_partial_refresh_keeps_last_good_and_reports_failure(self):
        first=self.refresh()
        self.data['otherlisted']=b'<html>unavailable</html>'
        with self.assertRaises(ValueError):self.refresh()
        self.assertEqual(d.view(self.root)['total'],6)
        self.assertEqual(d.view(self.root)['refresh']['state'],'FAILED')
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT revision FROM security_master_current').fetchone()[0],first['revision'])
        self.assertEqual(len(list((self.root/'security-directory/snapshots').iterdir())),2)

    def test_duplicate_and_invalid_dates_and_test_only_sources_are_refused(self):
        for mutate in ('duplicate','missing-footer','old','future','only-test'):
            data=files()
            if mutate=='duplicate':data['nasdaqlisted']=data['nasdaqlisted'].replace(b'Q01|',b'Q00|')
            elif mutate=='missing-footer':data['nasdaqlisted']=b'\n'.join(data['nasdaqlisted'].splitlines()[:-1])
            elif mutate=='old':data=files(footer='0101202621:31')
            elif mutate=='future':data=files(footer='1201202621:31')
            else:data['nasdaqlisted']=data['nasdaqlisted'].replace(b'|N|N|100|',b'|Y|N|100|')
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                d.parse(data['nasdaqlisted'],'nasdaqlisted',now=NOW,minimum=1)

    def test_refresh_retains_absent_records_and_never_regresses_source_time(self):
        self.data=files(n=20);self.refresh()
        self.data=files(n=19,footer='1107202621:31');self.refresh()
        with closing(self.a.connect()) as c:
            self.assertEqual(c.execute("SELECT active FROM market_security_master WHERE symbol='Q19'").fetchone()[0],0)
        self.data=files(n=20)
        with self.assertRaises(ValueError):self.refresh()
        self.data=files(n=1,footer='1108202601:31')
        with self.assertRaises(ValueError):self.refresh()
        self.assertEqual(d.view(self.root)['total'],22)

    def test_identical_content_has_same_revision_but_separate_refresh_occurrences(self):
        one=self.refresh();two=self.refresh()
        self.assertEqual(one['revision'],two['revision'])
        with closing(self.a.connect()) as c:self.assertEqual(c.execute('SELECT count(*) FROM security_master_refreshes').fetchone()[0],2)

    def test_filtered_pagination_preserves_selection_and_handles_literal_search(self):
        self.data=files(n=35);self.refresh()
        seen=[];text='network=C type=STOCK permission=PENDING q=Example'
        while True:
            page=d.view(self.root,text);seen.extend(r['symbol'] for r in page['rows'])
            self.assertEqual(page['total'],35)
            if not page['next_filters']:break
            text=' '.join(k+'='+__import__('shlex').quote(v) for k,v in page['next_filters'].items())
        self.assertEqual(len(seen),35);self.assertEqual(len(set(seen)),35)
        self.assertEqual(d.view(self.root,'q=%')['total'],0)
        self.assertEqual(d.view(self.root,'q="Example 12"')['total'],1)
        for bad in ('network=X','type=OPTION','permission=VERIFIED','q=A q=B','after=bad;sql'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):d.view(self.root,bad)

    def test_master_view_does_not_advance_or_rewrite_canonical_states(self):
        self.refresh()
        with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c,c:
            c.execute('CREATE TABLE canonical_pool_state(symbol,current_layer,updated_at)')
            c.execute("INSERT INTO canonical_pool_state VALUES('AAA','MASTER_UNIVERSE','old')")
        result=m.master_view(self.root,self.a,'network=A')
        self.assertEqual(result['rows'][0]['canonical_layer'],'MASTER_UNIVERSE')
        self.assertEqual(result['rows'][0]['ibkr_contract'],'UNRESOLVED')
        self.assertEqual(m.view(self.root,self.a,eligible=True)['rows'],[])
        with closing(sqlite3.connect(self.root/'trading_audit.sqlite3')) as c:self.assertEqual(c.execute('SELECT * FROM canonical_pool_state').fetchall(),[('AAA','MASTER_UNIVERSE','old')])

    def test_owner_universe_filter_runs_python_without_model_or_broker(self):
        from reporting.secretary_controls import process_controls
        self.refresh()
        self.a.append('owner','der-secretary',origin='USER',kind='CONTROL_INSTRUCTION',payload={'text':'/universe network=C type=STOCK'})
        with patch('subprocess.run') as run:process_controls(self.a,self.root,{'bot_username':'fixture'})
        run.assert_not_called()
        with closing(self.a.connect()) as c:
            row=c.execute("SELECT payload FROM secretary_events WHERE occurrence='owner:control:result'").fetchone()
            self.assertIn('筛选命中 3 项',json.loads(row[0])['summary'])
            self.assertEqual(c.execute('SELECT model,state FROM secretary_runs').fetchone(),('PYTHON_CONTROL','SUCCEEDED'))

    def test_download_response_has_an_owner_and_a_hard_read_bound(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.read.return_value=b'x'*2000001
        with patch('reporting.security_directory.urllib.request.urlopen') as open_url:
            open_url.return_value.__enter__.return_value=response
            with self.assertRaises(ValueError):d.fetch('nasdaqlisted')
            response.read.assert_called_once_with(2000001)
            open_url.return_value.__exit__.assert_called_once()
