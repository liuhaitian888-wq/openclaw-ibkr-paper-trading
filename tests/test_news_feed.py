import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from trading.news_feed import collect, capability, health_observation
from trading.auto_open_pipeline import PipelineConfig, raw_news_fixture, news_provider_status


class Event:
    def __iadd__(self, handler): self.handler = handler; return self
    def __isub__(self, handler): self.handler = None; return self


class FakeIB:
    def __init__(self, rows=None, account='DU123', providers=True):
        self.errorEvent = Event(); self.closed = False; self.rows = rows
        self.account = account; self.providers = providers; self.article_calls = 0
    async def connectAsync(self, *args, **kwargs):
        assert kwargs['readonly'] is True
        assert kwargs['clientId'] != 0
    def isConnected(self): return True
    def managedAccounts(self): return [self.account]
    async def reqNewsProvidersAsync(self):
        return [NS(code='REAL', name='Actual provider')] if self.providers else []
    async def qualifyContractsAsync(self, contract): return [NS(conId=123)]
    async def reqHistoricalNewsAsync(self, *args): return self.rows
    async def reqNewsArticleAsync(self, *args):
        self.article_calls += 1
        return NS(articleText='Actual article body', articleType=0)
    def disconnect(self): self.closed = True


class NewsTests(unittest.TestCase):
    def run_probe(self, ib):
        with patch.dict(sys.modules, ib_async=NS(StartupFetchNONE=0)):
            return asyncio.run(collect(ib, lambda *a: None, expected_account='DU123'))

    def test_connection_and_providers_do_not_prove_news(self):
        ib = FakeIB(rows=[])
        r = self.run_probe(ib)
        self.assertTrue(r['connected']); self.assertFalse(r['news_usable'])
        self.assertEqual(r['providers'][0]['status'], 'NO_HEADLINES_IN_WINDOW')
        self.assertTrue(ib.closed); self.assertEqual(ib.article_calls, 0)

    def test_timeout_differs_from_empty_and_permission(self):
        r = self.run_probe(FakeIB(rows=None))
        self.assertEqual(r['providers'][0]['status'], 'HEADLINE_TIMEOUT')
        self.assertFalse(r['news_usable'])

    def test_article_proof_and_expiry_and_fixture_rejection(self):
        row = NS(time=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), providerCode='REAL', articleId='a1', headline='Actual')
        ib = FakeIB(rows=[row]); r = self.run_probe(ib)
        self.assertTrue(r['news_usable']); self.assertTrue(ib.closed)
        self.assertEqual(health_observation(r)['state'], 'HEALTHY')
        r['completed_at'] = (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        self.assertFalse(capability(r))
        r['completed_at'] = datetime.now(timezone.utc).isoformat(); r['source_kind'] = 'FIXTURE'
        self.assertFalse(capability(r))

    def test_identity_failure_closes_connection(self):
        ib = FakeIB(account='U123'); r = self.run_probe(ib)
        self.assertEqual(r['status'], 'IDENTITY_MISMATCH'); self.assertTrue(ib.closed)
        self.assertFalse(r['providers']); self.assertFalse(r['news_usable'])

    def test_no_api_providers_not_guessed_connection_failure(self):
        r = self.run_probe(FakeIB(providers=False))
        self.assertEqual(r['status'], 'NO_API_PROVIDERS'); self.assertTrue(r['connected'])

    def test_permission_error_preserved(self):
        class Denied(FakeIB):
            async def reqHistoricalNewsAsync(self, *args):
                self.errorEvent.handler(1, 10000, 'No news permissions')
                return []
        r = self.run_probe(Denied())
        self.assertEqual(r['providers'][0]['status'], 'BROKER_PERMISSION_DENIED')
        self.assertFalse(r['news_usable'])

    @patch('trading.auto_open_pipeline.insert_event')
    def test_fixtures_explicit_and_never_live(self, insert):
        self.assertFalse(PipelineConfig().news_fixture_enabled)
        self.assertEqual(raw_news_fixture('r', PipelineConfig(), {}, {}), [])
        rows = raw_news_fixture('r', PipelineConfig(news_fixture_enabled=True), {}, {})
        self.assertTrue(rows)
        self.assertTrue(all(r['source_kind']=='FIXTURE' and not r['is_live'] for r in rows))
        with patch('trading.auto_open_pipeline.tws_available', return_value=True):
            providers = news_provider_status('r', PipelineConfig())
        self.assertTrue(all(not p['is_live'] for p in providers))
        self.assertFalse(next(p for p in providers if p['provider_type']=='IBKR_NEWS')['available'])

    def test_request_exception_always_disconnects(self):
        class Broken(FakeIB):
            async def reqNewsProvidersAsync(self): raise RuntimeError('failed')
        ib = Broken(); r = self.run_probe(ib)
        self.assertTrue(ib.closed); self.assertEqual(r['status'], 'PROBE_FAILED')
        self.assertFalse(r['news_usable'])

    def test_partial_provider_success_retains_denied_provider(self):
        class Partial(FakeIB):
            async def reqNewsProvidersAsync(self):
                return [NS(code='GOOD', name='Good'), NS(code='BAD', name='Bad')]
            async def reqHistoricalNewsAsync(self, conid, code, *args):
                if code == 'BAD':
                    self.errorEvent.handler(2, 1, 'Not subscribed')
                    return []
                return [NS(time=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), providerCode='GOOD', articleId='1', headline='Real')]
        r = self.run_probe(Partial())
        self.assertTrue(r['news_usable'])
        self.assertEqual([p['status'] for p in r['providers']], ['ARTICLE_VERIFIED','BROKER_PERMISSION_DENIED'])
        self.assertFalse(r['live_stream_verified']); self.assertFalse(r['strategy_news_ready'])

    def test_news_date_wire_format_and_old_article_rejected(self):
        class Old(FakeIB):
            async def reqHistoricalNewsAsync(self, conid, code, start, end, count):
                datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
                assert end == ''
                return [NS(time='2020-01-01 00:00:00', providerCode='REAL', articleId='old', headline='Old')]
        ib = Old(); r = self.run_probe(ib)
        self.assertEqual(r['providers'][0]['status'], 'OUTSIDE_REQUESTED_WINDOW')
        self.assertEqual(r['providers'][0]['headlines'], [])
        self.assertEqual(len(r['providers'][0]['returned_headlines']), 1)
        self.assertEqual(ib.article_calls, 0); self.assertFalse(r['news_usable'])
