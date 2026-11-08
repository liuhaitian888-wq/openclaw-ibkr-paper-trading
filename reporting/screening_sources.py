"""Bounded public research sources. Missing fields stay null; no broker access."""
from datetime import datetime, timezone
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

NASDAQ = 'https://api.nasdaq.com/api/screener/stocks?download=true'
NASDAQ_DATE = 'https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0'
YAHOO = 'https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=most_actives&count=250&start='
SEC_MAPPING = 'https://www.sec.gov/files/company_tickers.json'


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(str(value).replace('$', '').replace(',', '').replace('%', '').strip())
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


class Backoff(RuntimeError):
    pass


def fetch(url, *, sec_email=None, retry=None, now=None):
    now = time.time() if now is None else now
    retry = {} if retry is None else retry
    host = urlsplit(url).hostname
    if urlsplit(url).scheme != 'https' or host not in ('api.nasdaq.com', 'query1.finance.yahoo.com', 'www.sec.gov', 'data.sec.gov'):
        raise PermissionError('Fixed public source host required')
    if retry.get(url, {}).get('not_before', 0) > now:
        raise Backoff('Source cooldown is active')
    ua = 'buy-der-readonly-screening/1.0'
    if host in ('www.sec.gov', 'data.sec.gov'):
        if not isinstance(sec_email, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', sec_email):
            raise PermissionError('Configured SEC contact required')
        ua += ' '+sec_email

    class SameHost(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlsplit(newurl).scheme != 'https' or urlsplit(newurl).hostname != host:
                if fp is not None:
                    fp.close()
                raise PermissionError('Cross-host redirect refused')
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    try:
        with build_opener(SameHost()).open(Request(url, headers={'User-Agent': ua, 'Accept': 'application/json'}), timeout=10) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError('Source response exceeds 5MB')
        retry.pop(url, None)
        return raw
    except HTTPError as exc:
        code = exc.code
        exc.close()
        retry[url] = dict(not_before=now+(3600 if code == 403 else 900 if code == 429 else 120), http_status=code)
        raise
    except (OSError, TimeoutError):
        retry[url] = dict(not_before=now+120, http_status=None)
        raise


def nasdaq(raw, date_raw):
    body = json.loads(raw)['data']
    rows = body.get('rows') or body.get('table', {}).get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ValueError('Bounded Nasdaq screener rows required')
    metadata = json.loads(date_raw)['data']
    match = re.search(r'as of (\w+ \d{1,2}, \d{4})', str(metadata.get('asof', '')))
    date = datetime.strptime(match[1], '%b %d, %Y').date().isoformat() if match else None
    date_rows = metadata.get('rows') or metadata.get('table', {}).get('rows') or []
    lookup = {r.get('symbol'): number(r.get('lastsale')) for r in date_rows}
    sample = [r for r in rows if r.get('symbol') in ('AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL')]
    matched = len(sample) >= 3 and all(number(r.get('lastsale')) is not None and number(r.get('lastsale')) == lookup.get(r['symbol']) for r in sample)
    if not matched:
        date = None
    result = []; seen = set()
    for row in rows:
        symbol = row.get('symbol')
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.$^=/+\-]{0,31}', symbol) or symbol in seen:
            raise ValueError('Ambiguous Nasdaq symbol')
        seen.add(symbol)
        result.append(dict(symbol=symbol, price=number(row.get('lastsale')), volume=number(row.get('volume')),
                           average_volume=None, average_volume_window=None, market_cap=number(row.get('marketCap')),
                           sector=row.get('sector'), currency='USD' if str(row.get('lastsale', '')).startswith('$') else 'UNKNOWN',
                           price_date=date, price_at=None, time_quality='DATE_ONLY_CROSS_ENDPOINT_SAMPLE' if date else 'UNKNOWN',
                           source='NASDAQ_SCREENER', coverage='PROVIDER_STOCK_SCREEN_NOT_ALL_LISTINGS',
                           trailing_pe=None, quote_type='RESEARCH_LAST_SALE'))
    total = number(body.get('totalrecords'))
    return result, dict(rows=len(result), provider_total=total, partial=bool(total and total > len(result)),
                        date_metadata_price_samples_match=matched, date_only=date, realtime_verified=False)


def yahoo(raw):
    body = json.loads(raw)['finance']['result'][0]
    quotes = body.get('quotes')
    if not isinstance(quotes, list) or len(quotes) > 250:
        raise ValueError('Bounded Yahoo predefined screen page required')
    rows = []; seen = set()
    for q in quotes:
        sym = q.get('symbol')
        if not isinstance(sym, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.$^=/+\-]{0,31}', sym) or sym in seen:
            raise ValueError('Ambiguous Yahoo symbol')
        seen.add(sym)
        at = number(q.get('regularMarketTime'))
        rows.append(dict(symbol=sym, price=number(q.get('regularMarketPrice')), volume=number(q.get('regularMarketVolume')),
                         average_volume=number(q.get('averageDailyVolume3Month')), average_volume_window='3_MONTH',
                         market_cap=number(q.get('marketCap')), currency=q.get('currency', 'UNKNOWN'),
                         price_at=at, price_date=datetime.fromtimestamp(at, timezone.utc).date().isoformat() if at else None,
                         time_quality='PROVIDER_TIMESTAMP' if at else 'UNKNOWN', source='YAHOO_MOST_ACTIVE',
                         coverage='PREDEFINED_TOP_MOST_ACTIVE_NOT_FULL_UNIVERSE', sector=q.get('sector'),
                         trailing_pe=number(q.get('trailingPE')), quote_type=q.get('quoteType', 'UNKNOWN')))
    return rows, dict(provider_total=body.get('total'), rows=len(rows), partial=True, realtime_verified=False)


def sec_mapping(raw):
    records = json.loads(raw)
    if not isinstance(records, dict) or len(records) > 40000:
        raise ValueError('Bounded SEC ticker mapping required')
    result = {}; ambiguous = set()
    for row in records.values():
        sym = row.get('ticker'); cik = row.get('cik_str')
        if isinstance(sym, str) and isinstance(cik, int) and cik > 0:
            if sym in result and result[sym] != cik:
                ambiguous.add(sym)
            result[sym] = cik
    return {s: cik for s, cik in result.items() if s not in ambiguous}


def sec_frame(raw, *, tag, unit, period):
    body = json.loads(raw)
    if body.get('tag') != tag or body.get('uom') != unit or body.get('ccp') != period or body.get('taxonomy') != 'us-gaap':
        raise ValueError('SEC concept/unit/period mismatch')
    data = body.get('data')
    if not isinstance(data, list) or len(data) > 30000:
        raise ValueError('Bounded SEC frame required')
    result = {}; seen = set()
    for r in data:
        cik = r.get('cik'); value = number(r.get('val'))
        if not isinstance(cik, int) or cik <= 0 or cik in seen:
            raise ValueError('Ambiguous SEC issuer frame')
        seen.add(cik)
        if value is None or not r.get('end') or not r.get('accn'):
            continue
        end = datetime.strptime(r['end'], '%Y-%m-%d').date().isoformat()
        result[cik] = dict(value=value, end=end, start=r.get('start'), accession=r['accn'],
                           tag=tag, unit=unit, period=period, filed_at=None,
                           point_in_time_verified=False, scope='ISSUER_NOT_SHARE_CLASS')
    return result


def completed_quarter(now):
    d = datetime.fromtimestamp(now, timezone.utc)
    q = (d.month-1)//3  # preceding completed calendar quarter
    return (d.year, q) if q else (d.year-1, 4)
