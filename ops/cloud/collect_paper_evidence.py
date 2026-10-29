"""Scheduled read-only Paper evidence; never publishes production readiness."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.live_observation import probe, PaperIdentityError
from reporting.paper_signal_report import publish_report


def main():
    os.umask(0o077)
    root = Path.home()/'.local/state/openclaw'
    config_path = Path.home()/'.config/openclaw/paper-observer.json'
    if config_path.stat().st_mode & 0o077:
        raise PermissionError('Observer config must be mode 0600')
    config = json.loads(config_path.read_text())
    account = config['expected_account']
    if not isinstance(account, str) or not account.startswith('DU') or not account.isalnum():
        raise ValueError('An exact Paper account is required before opening a connection')
    symbols = tuple(config.get('symbols', ['AAPL','MSFT','QQQ']))
    if not symbols or len(symbols)>5 or any(not isinstance(s,str) or not s.isalpha() for s in symbols):
        raise ValueError('Use one to five simple US stock/ETF symbols')
    try:
        result = probe('127.0.0.1', 4002, 18765, 20,
                       expected_account=account, symbols=())
        # Independent broker account/order/position truth remains. L1 is owned
        # exclusively by paper-safety; this observer must never acquire it.
        result['market_data_owner']='ibkr-paper-safety.service'
        result['market_data_requests_sent']=0
        result['status'] = 'READBACK_COMPLETE' if result.get('complete') else 'INCOMPLETE'
    except Exception as exc:
        result = dict(status='AUTH_OR_CONNECTION_REQUIRED', error_type=type(exc).__name__,
                      complete=False, environment='PAPER',
                      failure_class='IDENTITY_MISMATCH' if isinstance(exc, PaperIdentityError) else 'AUTH_OR_CONNECTION_UNVERIFIED')
    result['observed_at'] = datetime.now(timezone.utc).isoformat()
    result['grants_trading_permission'] = False
    history = root/'observations'/result['observed_at'][:10]
    history.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%H%M%S.%f')
    with (history/(stamp+'.json')).open('x') as handle:
        json.dump(result, handle, indent=2)
    latest = root/'runtime/paper-observer.latest.json'
    temporary = latest.with_suffix('.tmp')
    with temporary.open('w') as handle:
        json.dump(result, handle, indent=2)
    temporary.replace(latest)
    # Separate read-only output; never changes probe success or trading gates.
    report = publish_report(root, config)
    print('PAPER_SHADOW_REPORT_' + report['status'])
    print(result['status'])
    return 0 if result['status']=='READBACK_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
