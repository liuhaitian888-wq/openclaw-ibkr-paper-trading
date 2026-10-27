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
from reporting.paper_model_reference import existing_model, universe_reference


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
    if not isinstance(resources, dict):
        return False
    return (item.get('source') == 'REAL_IBKR' and item.get('environment') == 'PAPER'
            and item.get('account_id') == account and item.get('complete') is True
            and item.get('status') == 'READBACK_COMPLETE'
            and resources.get('worker_stopped') is True
            and resources.get('reader_stopped') is True
            and resources.get('connected_after_close') is False)


def valid_quote(item, symbol, observed):
    quotes = item.get('quotes') or {}
    if not isinstance(quotes, dict):
        return None
    quote = quotes.get(symbol, {})
    if not isinstance(quote, dict) or type(quote.get('data_type')) is not int or quote.get('data_type') != 1:
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


def session_state(item, account, symbols):
    codes = []
    for error in item.get('raw_errors', []):
        args = error.get('raw_callback_arguments', []) if isinstance(error, dict) else []
        code = args[1] if len(args) >= 3 and type(args[1]) is int else args[0] if args else None
        if type(code) is int:
            codes.append(code)
    connections = [code for code in codes if code in (1100,1101,1102,1300)]
    observed = checked_time(item)
    if (item.get('account_id') not in (None, account) or item.get('environment') not in (None,'PAPER')
            or item.get('failure_class') == 'IDENTITY_MISMATCH'):
        state = 'IDENTITY_UNVERIFIED'
    elif 10197 in codes:
        state = 'MARKET_DATA_COMPETITION'
    elif connections and connections[-1] in (1100,1300):
        state = 'BROKER_CONNECTION_LOST'
    elif connections and connections[-1] == 1101:
        state = 'READBACK_AND_RESUBSCRIBE_REQUIRED'
    elif not identity_ok(item, account):
        state = 'AUTH_OR_CONNECTION_UNVERIFIED'
    elif observed is None or not all(valid_quote(item,symbol,observed) for symbol in symbols):
        state = 'MARKET_DATA_UNAVAILABLE'
    else:
        state = 'PAPER_DATA_VERIFIED'
    return dict(state=state, error_codes=list(dict.fromkeys(codes)),
                exact_paper_verified=identity_ok(item,account),
                cause_attribution='BROKER_ERROR_CODE' if 10197 in codes or connections else 'OBSERVED_SYMPTOM_ONLY',
                grants_trading_permission=False)


def session_timeline(dated, account, symbols):
    events=[]; prior=None; prior_at=None; fault_at=None;seen=set()
    for at,item in dated:
        current=session_state(item,account,symbols)
        identity=(at,current['state'],tuple(current['error_codes']))
        if identity in seen:
            continue
        seen.add(identity)
        if prior_at and (at-prior_at).total_seconds()>MAX_AGE:
            events.append(dict(observed_at=at.isoformat(),state='OBSERVATION_GAP',
                               last_observed_at=prior_at.isoformat(),transition='SAMPLING_GAP_CAUSE_UNKNOWN',
                               elapsed_between_observations_seconds=(at-prior_at).total_seconds()))
            prior='OBSERVATION_GAP';fault_at=at
        if current['state'] != prior:
            transition='BASELINE_OBSERVED' if prior is None else 'OBSERVED_CHANGE'
            if current['state'] == 'PAPER_DATA_VERIFIED' and prior is not None:
                transition='OBSERVED_RECOVERY_RECONCILIATION_NOT_APPROVED'
            event=dict(current,observed_at=at.isoformat(),previous_state=prior,transition=transition)
            if current['state'] != 'PAPER_DATA_VERIFIED':
                if fault_at is None:fault_at=at
            elif fault_at is not None:
                event['observed_fault_span_seconds']=(at-fault_at).total_seconds();fault_at=None
            events.append(event)
        prior=current['state'];prior_at=at
    return dict(source='private observations/YYYY-MM-DD/*.json; reconstructable sampled evidence',
                observation_window_start=dated[0][0].isoformat() if dated else None,
                observation_window_end=dated[-1][0].isoformat() if dated else None,
                sampling_interval_seconds=PERIOD, continuous_event_capture=False,
                exact_outage_duration_known=False, automatic_relogin_or_takeover=False,
                transitions=events[-40:])


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
            current_session = session_state(latest,expected_account,symbols)
            if current_session['state'] != 'PAPER_DATA_VERIFIED':
                status = current_session['state']
    else:
        status = 'NO_DATA'

    for symbol in symbols:
        samples = []
        current_quote = None
        for at, item in dated:
            quote = (valid_quote(item, symbol, at)
                     if session_state(item,expected_account,symbols)['state'] == 'PAPER_DATA_VERIFIED' else None)
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
        positions = dated[-1][1].get('positions',[]) if dated and status == 'CURRENT' else []
        row['existing_model'] = existing_model([],None,symbol,positions)
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
            row['existing_model'] = existing_model(samples,current_quote,symbol,positions)
        result['symbols'][symbol] = row
    if status == 'CURRENT':
        rows = result['symbols'].values()
        status = ('DATA_UNAVAILABLE' if any(row['signal'] is None for row in rows) else
                  'WARMING_UP' if any(row['signal'] == 'WARMING_UP' for row in rows) else 'SHADOW_READY')
    result['status'] = status
    result['session_history'] = session_timeline(dated,expected_account,symbols)
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
    lines.extend(['## 已有模型参考输出','',
                  '复用 classic_conservative_trend 与原CLI参考参数；配置/股票池尚未正式批准。只评估，不记录虚拟成交，不将券商外部持仓自动认领为策略持仓。','',
                  '| 股票 | 模型建议 | 原因 | 券商持仓数量 |','|---|---|---|---:|'])
    for symbol,row in report['symbols'].items():
        model=row['existing_model'];decision=model['decision'] or {}
        lines.append(f"| {symbol} | {decision.get('action','不可用')} | {decision.get('reason','等待有效Paper数据')} | {model.get('broker_exposure_quantity') or '—'} |")
    reference=report.get('universe_reference',{})
    lines.extend(['',f"参考股票池：{reference.get('status','未计算')}；CSV基本面时间未知，不能当作新鲜入池审批。",'',
                  '## 会话与数据恢复记录','',
                  '由已保存原始观察重建；五分钟采样会遗漏短暂断线，检测时间不等于实际故障开始。恢复仅表示回读/数据恢复，未批准交易恢复。','',
                  '| 检测时间（UTC） | 状态 | 券商错误码 | 变化 |','|---|---|---|---|'])
    for event in report['session_history']['transitions']:
        lines.append(f"| {event['observed_at']} | {event['state']} | {event.get('error_codes',[])} | {event['transition']} |")
    lines.append('')
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
            row['existing_model']['decision']=None
        result['session_history']['source_file_invalid']=True
    result['universe_reference']=universe_reference(config['symbols'])
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
