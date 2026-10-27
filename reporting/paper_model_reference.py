"""Existing model/filter reference evaluation only; no execution or position adoption."""
from dataclasses import asdict
import hashlib

from trading.market_data import Bar, Quote
from trading.strategy_modules import ConservativeTrendConfig, ConservativeTrendModule
from trading.strategy import ValueFilterConfig, ValuePoolFilter
from trading.universe import DEFAULT_UNIVERSE_FILE, UniverseSelectionConfig, load_universe, select_universe


def existing_model(samples, quote, symbol, broker_positions=()):
    # Existing run_pool_strategy_module.py CLI defaults, NOT approved live settings.
    config = ConservativeTrendConfig(fast_window=2, slow_window=3,
                                    profit_target_pct=.0015, stop_loss_pct=.0015,
                                    min_gap_pct=.0001, cooldown_steps=0)
    result = dict(name=ConservativeTrendModule.name, configuration=asdict(config),
                  configuration_source='scripts/run_pool_strategy_module.py CLI defaults',
                  configuration_approved=False, execution_authorized=False,
                  input_kind='sampled bid/ask midpoint; not trade OHLC',
                  broker_position_adopted_as_strategy_owned=False,
                  broker_exposure_quantity=next((p.get('position') for p in broker_positions if p.get('symbol') == symbol), None),
                  decision=None,
                  execution_blockers=['REPORT_ONLY', 'UNAPPROVED_CONFIGURATION_AND_UNIVERSE',
                                      'OWNERSHIP_RISK_RECONCILIATION_NOT_APPROVED'])
    if not samples or quote is None:
        return result
    at = quote['received_at']
    from datetime import datetime
    market_quote = Quote(symbol, (quote['bid']+quote['ask'])/2, datetime.fromisoformat(at),
                         'IBKR_MIDPOINT_SAMPLED_REPORT_ONLY', bid=quote['bid'], ask=quote['ask'])
    bars = [Bar(symbol,300,t,t,mid,mid,mid,mid) for t, mid in samples]
    module = ConservativeTrendModule([symbol],config)
    result['decision'] = asdict(module.evaluate(symbol=symbol,quote=market_quote,bars=bars,step=len(bars)))
    # Deliberately no record_order_decision(): a proposal is never a fill.
    return result


def universe_reference(symbols):
    try:
        path = DEFAULT_UNIVERSE_FILE
        if path.stat().st_size > 1048576:
            raise ValueError('Reference universe too large')
        selection = select_universe(load_universe(path), ValuePoolFilter(ValueFilterConfig()),
                                    UniverseSelectionConfig(), requested_symbols=symbols)
        records = []
        for row in selection.records:
            if row['symbol'] in symbols:
                row = dict(row); row['reference_pass'] = row.pop('approved'); records.append(row)
        return dict(status='REFERENCE_ONLY_NOT_APPROVED', source='data/us_equity_universe.csv',
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    fundamentals_freshness='UNKNOWN_NO_AS_OF_DATE', records=records,
                    grants_universe_approval=False)
    except (OSError, ValueError):
        return dict(status='REFERENCE_UNAVAILABLE', grants_universe_approval=False,records=[])
