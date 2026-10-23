"""Explicit, bounded Paper account/L1 readback; no order submission methods."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reporting.live_observation import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-account', required=True)
    parser.add_argument('--symbols', default='AAPL,MSFT,QQQ')
    args = parser.parse_args()
    if not args.expected_account.startswith('DU') or not args.expected_account.isalnum():
        parser.error('An exact Paper account identifier is required')
    symbols = tuple(s.strip().upper() for s in args.symbols.split(',') if s.strip())
    if len(symbols) > 5 or any(not s.isalpha() for s in symbols):
        parser.error('Use at most five simple US stock/ETF symbols')
    result = probe(host='127.0.0.1', port=4002, client_id=18765,
                   timeout=20, symbols=symbols, expected_account=args.expected_account)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A complete account readback and L1 entitlements are separate assertions.
    quote_ok = bool(symbols) and all(
        result['quotes'].get(s, {}).get('data_type') == 1
        and result['quotes'].get(s, {}).get('bid', 0) > 0
        and result['quotes'].get(s, {}).get('ask', 0) > 0 for s in symbols)
    return 0 if result.get('complete') and quote_ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
