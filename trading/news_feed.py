"""Actual IBKR news evidence. No order methods, inferred subscriptions or fixtures."""
import asyncio
from datetime import datetime, timedelta, timezone
from trading.news_article_evidence import retain


def utc_now():
    return datetime.now(timezone.utc)


def capability(result, now=None, max_age=300):
    """Recent historical retrieval proof; does not prove streaming/fresh event coverage."""
    now = now or utc_now()
    try:
        age = (now - datetime.fromisoformat(result['completed_at'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    return bool(result.get('source_kind') == 'BROKER_API' and result.get('identity_verified')
                and 0 <= age <= max_age and any(
                    p.get('status') == 'ARTICLE_VERIFIED' and p.get('headlines')
                    and p.get('article_sha256') for p in result.get('providers', [])))


async def collect(ib, stock_factory, *, expected_account, host='127.0.0.1', port=4002,
                  client_id=19871, symbol='NVDA', timeout=8):
    if not expected_account.startswith('DU') or not expected_account.isalnum():
        raise ValueError('Exact Paper account required')
    if client_id <= 0 or port != 4002 or host != '127.0.0.1':
        raise ValueError('Dedicated nonzero client and local Paper endpoint required')
    if not symbol.isalpha() or len(symbol) > 8:
        raise ValueError('Simple stock symbol required')
    result = dict(source_kind='BROKER_API', library='ib_async==2.1.0', symbol=symbol,
                  started_at=utc_now().isoformat(), connected=False, identity_verified=False,
                  providers=[], errors=[], status='UNVERIFIED', news_usable=False,
                  expected_account=expected_account, live_stream_verified=False,
                  strategy_news_ready=False, query_window_days=2,
                  orders_submitted=0, grants_trading_permission=False)
    errors = result['errors']
    def on_error(req_id, code, message, *args):
        errors.append(dict(req_id=req_id, code=code, message=str(message)[:1000]))
    ib.errorEvent += on_error
    try:
        # No order synchronization, autobind, account subscriptions or execution requests.
        from ib_async import StartupFetchNONE
        await asyncio.wait_for(ib.connectAsync(host, port, clientId=client_id,
            readonly=True, timeout=timeout, fetchFields=StartupFetchNONE), timeout + 1)
        result['connected'] = ib.isConnected()
        if ib.managedAccounts() != [expected_account]:
            result['status'] = 'IDENTITY_MISMATCH'
            return result
        result['identity_verified'] = True
        providers = await asyncio.wait_for(ib.reqNewsProvidersAsync(), timeout)
        result['provider_discovery_completed'] = True
        if not providers:
            result['status'] = 'NO_API_PROVIDERS'
            return result
        contracts = await asyncio.wait_for(ib.qualifyContractsAsync(
            stock_factory(symbol, 'SMART', 'USD')), timeout)
        if len(contracts) != 1 or not contracts[0].conId:
            result['status'] = 'CONTRACT_UNRESOLVED'
            return result
        result['con_id'] = contracts[0].conId
        end = utc_now()
        start = end-timedelta(days=2)
        # News API uses dashed dates and ignores end when start is supplied.
        result['requested_start'] = start.strftime('%Y-%m-%d %H:%M:%S')
        result['requested_end'] = ''
        for provider in providers[:10]:
            entry = dict(code=provider.code, name=provider.name, status='UNVERIFIED',
                         headlines=[], article_sha256=None, article_bytes=0)
            result['providers'].append(entry)
            error_start = len(errors)
            try:
                rows = await asyncio.wait_for(ib.reqHistoricalNewsAsync(
                    contracts[0].conId, provider.code, result['requested_start'], '', 3), timeout)
                if rows is None:
                    entry['status'] = 'HEADLINE_TIMEOUT'
                elif not rows:
                    entry['status'] = 'NO_HEADLINES_IN_WINDOW'
                else:
                    entry['returned_headlines'] = [dict(time=str(r.time), provider_code=r.providerCode,
                        article_id=r.articleId, headline=r.headline,
                        source_kind='BROKER_API', retrieved_at=utc_now().isoformat()) for r in rows]
                    entry['headlines'] = [r for r in entry['returned_headlines']
                        if r['provider_code']==provider.code and in_window(r['time'], start, end)]
                    entry['out_of_window_count'] = len(rows)-len(entry['headlines'])
                    if not entry['headlines']:
                        entry['status'] = 'OUTSIDE_REQUESTED_WINDOW'
                        entry['errors'] = errors[error_start:]
                        continue
                    entry['status'] = 'HEADLINES_VERIFIED'
                    latest = next(r for r in rows if r.articleId == entry['headlines'][0]['article_id'] and r.providerCode==provider.code)
                    article = await asyncio.wait_for(ib.reqNewsArticleAsync(
                        latest.providerCode, latest.articleId), timeout)
                    if article and article.articleText.strip():
                        entry.update(status='ARTICLE_VERIFIED', **retain(article.articleText,
                            provider=latest.providerCode, article_id=latest.articleId,
                            article_type=article.articleType, retrieved_at=utc_now(), published_at=latest.time))
            except asyncio.TimeoutError:
                entry['status'] = 'REQUEST_TIMEOUT'
            except Exception as exc:
                entry.update(status='REQUEST_FAILED', error_type=type(exc).__name__)
            entry['errors'] = errors[error_start:]
            # Preserve the exact broker error; never label an empty result as unsubscribed.
            if any('permission' in e['message'].lower() or 'subscrib' in e['message'].lower()
                   for e in entry['errors']):
                entry['status'] = 'BROKER_PERMISSION_DENIED'
        result['status'] = 'RETRIEVAL_COMPLETE'
    except asyncio.TimeoutError:
        result['status'] = 'REQUEST_TIMEOUT'
    except Exception as exc:
        result.update(status='PROBE_FAILED', error_type=type(exc).__name__)
    finally:
        ib.disconnect()
        ib.errorEvent -= on_error
        result['completed_at'] = utc_now().isoformat()
        result['news_usable'] = capability(result)
    return result


def load_evidence(path):
    import json
    try:
        with path.open() as handle:
            result = json.load(handle)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def health_observation(result, now=None):
    valid = capability(result, now)
    return dict(state='HEALTHY' if valid else 'DEGRADED',
                freshness='FRESH' if valid else 'UNKNOWN',
                reason='Broker headline and article verified' if valid else 'News retrieval unverified',
                observed_at=result.get('completed_at'), last_success=result.get('completed_at') if valid else None)


def in_window(value, start, end):
    """Reject malformed, future or stale broker publication timestamps."""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return start <= parsed <= end
    except (TypeError, ValueError):
        return False
