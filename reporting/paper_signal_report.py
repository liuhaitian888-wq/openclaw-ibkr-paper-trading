"""Read stored Paper observations and reuse the MA engine for shadow analysis.

No broker, execution, notification or database client. Midpoint samples are not
trade bars, a complete L1 feed, or permission to execute a signal.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import tempfile

from trading.market_data import Bar
from trading.strategy import MovingAverageConfig, MovingAverageSignalEngine


PERIOD = 300
MAX_GAP = 450
MAX_AGE = 600
MAX_FILES = 256
MAX_BYTES = 262144


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def checked_time(item):
    try:
        return timestamp(item.get('observed_at'))
    except (ValueError, TypeError, AttributeError):
        return None


def identity_ok(item, account):
    resources = item.get('resources') or {}
    return (item.get('source') == 'REAL_IBKR' and item.get('environment') == 'PAPER'
            and item.get('account_id') == account and item.get('complete') is True
            and item.get('status') == 'READBACK_COMPLETE'
            and resources.get('worker_stopped') is True
            and resources.get('reader_stopped') is True
            and resources.get('connected_after_close') is False)


def valid_quote(item, symbol, observed):
    quote = (item.get('quotes') or {}).get(symbol, {})
    if not isinstance(quote, dict) or quote.get('data_type') != 1:
        return None
    bid, ask = quote.get('bid'), quote.get('ask')
    if not all(type(x) in (int, float) and math.isfinite(x) and 0 < x < 1e9 for x in (bid, ask)):
        return None
    if ask < bid:
        return None
    try:
        age = (observed-timestamp(quote.get('received_at'))).total_seconds()
    except (ValueError, TypeError):
        return None
    if not -2 <= age <= 60:
        return None
    return quote


def build_report(observations, expected_account, symbols, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(expected_account, str) or not expected_account.startswith('DU') or not expected_account.isalnum():
        raise ValueError('Exact Paper account required')
    if not symbols or len(symbols) > 5 or any(not isinstance(s, str) or not s.isalpha() or not s.isupper() for s in symbols):
        raise ValueError('Use one to five uppercase stock/ETF symbols')
    configuration = MovingAverageConfig()
    result = dict(created_at=now.isoformat(), observed_at=None, status='NO_DATA',
                  paper_only=True, report_only=True, grants_trading_permission=False,
                  orders_submitted=0, sampling='5-minute bid/ask midpoint samples; not OHLC or complete L1',
                  strategy='existing MovingAverageSignalEngine', configuration=asdict(configuration),
                  symbols={})
    dated = [(checked_time(item), item) for item in observations]
    if any(at is None for at, _ in dated):
        status = 'INVALID_TIME'
        dated = []
    elif dated:
        dated.sort(key=lambda pair: pair[0])
        latest_at, latest = dated[-1]
        result['observed_at'] = latest_at.isoformat()
        age = (now-latest_at).total_seconds()
        if age < -5:
            status = 'INVALID_TIME'
        elif age > MAX_AGE:
            status = 'STALE'
        elif not identity_ok(latest, expected_account):
            status = ('AUTH_OR_CONNECTION_REQUIRED' if latest.get('status') == 'AUTH_OR_CONNECTION_REQUIRED'
                      else 'PAPER_EVIDENCE_UNVERIFIED')
        else:
            status = 'CURRENT'
    else:
        status = 'NO_DATA'

    for symbol in symbols:
        samples = []
        current_quote = None
        for at, item in dated:
            quote = valid_quote(item, symbol, at) if identity_ok(item, expected_account) else None
            if quote is None or (now-at).total_seconds() < -5:
                samples = []
                current_quote = None
                continue
            if samples and (at-samples[-1][0]).total_seconds() > MAX_GAP:
                samples = []
            midpoint = (quote['bid']+quote['ask'])/2
            if samples and int(at.timestamp())//PERIOD == int(samples[-1][0].timestamp())//PERIOD:
                samples[-1] = (at, midpoint)
            else:
                samples.append((at, midpoint))
            samples = samples[-32:]
            current_quote = quote
        row = dict(sample_count=len(samples), signal=None, reason='Current verified real-time data required',
                   short_ma=None, long_ma=None)
        if status == 'CURRENT' and current_quote:
            engine = MovingAverageSignalEngine(configuration)
            decision = None
            for at, midpoint in samples:
                # Point-value adapter only: these are explicitly NOT market OHLC bars.
                decision = engine.update(Bar(symbol, PERIOD, at, at, midpoint, midpoint, midpoint, midpoint))
            row.update(bid=current_quote['bid'], ask=current_quote['ask'],
                       received_at=current_quote['received_at'], data_type=1,
                       signal=decision.action if len(samples) >= configuration.long_window else 'WARMING_UP',
                       reason=decision.reason, short_ma=decision.short_ma, long_ma=decision.long_ma)
        result['symbols'][symbol] = row
    if status == 'CURRENT':
        rows = result['symbols'].values()
        status = ('DATA_UNAVAILABLE' if any(row['signal'] is None for row in rows) else
                  'WARMING_UP' if any(row['signal'] == 'WARMING_UP' for row in rows) else 'SHADOW_READY')
    result['status'] = status
    return result


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.paper-report-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_markdown(report):
    lines = ['# Paper 行情与均线影子报告', '', f"生成时间（UTC）：{report['created_at']}",
             f"采集时间（UTC）：{report['observed_at'] or '无'}", f"状态：**{report['status']}**", '',
             '仅分析已存 Paper 观察文件；非交易指令，未启动策略下单。',
             'MA3/5 + 两次确认复用现有引擎；输入是五分钟 bid/ask 中间价采样，并非成交价K线或完整L1。',
             '断线/无效数据清空连续样本；样本不足需等待。当前报价最多允许10分钟观察年龄，不能用于低延迟执行。', '',
             '| 股票 | Bid | Ask | 连续样本 | 影子信号 | 短均线 | 长均线 |',
             '|---|---:|---:|---:|---|---:|---:|']
    for symbol, row in report['symbols'].items():
        values = [symbol, row.get('bid', '—'), row.get('ask', '—'), row['sample_count'],
                  row['signal'] or '不可用', row['short_ma'], row['long_ma']]
        lines.append('| ' + ' | '.join('—' if v is None else str(round(v, 4)) if isinstance(v, float) else str(v) for v in values) + ' |')
    lines.extend(['', 'SHADOW_READY 仅表示影子计算已有样本；不代表可交易、盈利或全部策略验收通过。', ''])
    return '\n'.join(lines)


def write_report(root, config, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    paths = []
    for date in (now.date()-timedelta(days=1), now.date()):
        folder = root/'observations'/date.isoformat()
        if folder.is_symlink():
            raise ValueError('Symlink source refused')
        paths.extend(folder.glob('*.json'))
    observations = []
    invalid_file = False
    for path in sorted(paths)[-MAX_FILES:]:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                raise ValueError('Invalid source file')
            with path.open() as handle:
                item = json.loads(handle.read(MAX_BYTES+1))
            if not isinstance(item, dict):
                raise ValueError('Invalid source payload')
            observations.append(item)
        except (OSError, ValueError):
            invalid_file = True
    result = build_report(observations, config['expected_account'], config['symbols'], now)
    if invalid_file:
        result['status'] = 'SOURCE_FILE_INVALID'
        for row in result['symbols'].values():
            row.update(signal=None, reason='Source file requires inspection')
            row.pop('bid', None); row.pop('ask', None)
    target = root/'reports/paper_shadow'
    atomic_write(target/'latest.json', json.dumps(result, indent=2, allow_nan=False)+'\n')
    atomic_write(target/'latest.md', render_markdown(result))
    return result


def publish_report(root, config):
    """Optional report failure must never turn a successful broker probe into failure."""
    try:
        return write_report(root, config)
    except Exception:
        return {'status': 'REPORT_WRITE_FAILED'}
