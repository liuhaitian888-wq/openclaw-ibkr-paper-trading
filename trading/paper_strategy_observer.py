"""Existing K-line strategy in monitor-only mode. No broker submission methods."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import threading
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trading.market_data import Bar, Quote
from trading.strategy_modules import ConservativeTrendConfig, ConservativeTrendModule
from trading.risk import RiskEngine, RiskLimits
from trading.models import TradeProposal
from trading.symbol_health import classify_symbol, session_for_symbol
from trading.signal_scheduler import SignalScheduler, catalog_bindings
from strategies import MarketData, PortfolioState
from trading.price_normalizer import normalize_order_price


class PaperStrategyObserver:
    def __init__(self, symbols, config, report_path, *, max_order_value=200, max_risk=10, signal_configurations=None):
        fields=ConservativeTrendConfig.__dataclass_fields__
        self.config=ConservativeTrendConfig(**{k:v for k,v in config.items() if k in fields})
        self.module=ConservativeTrendModule(symbols,self.config)
        self.risk=RiskEngine(RiskLimits(True,frozenset(symbols),1,min(200,max_order_value),max_risk))
        self.path=Path(report_path)
        self.bars={s:{} for s in symbols};self.history_complete=set();self.contracts={}
        self.last_report={}
        self.lock=threading.RLock()
        self.scheduler=SignalScheduler(catalog_bindings(signal_configurations or {},symbols))
        self.catalog_report=None
        self.pending={s:{} for s in symbols}

    def history(self, symbol, raw, now):
        try:
            start=int(raw.date); end=start+60
            values=[float(getattr(raw,k)) for k in ('open','high','low','close')]
            if (start%60 or start>now or not all(math.isfinite(v) and v>0 for v in values)
                    or not math.isfinite(float(raw.volume)) or raw.volume<0
                    or values[1]<max(values) or values[2]>min(values)):
                return False
        except (ValueError,TypeError,AttributeError):
            return False
        for old in list(self.pending[symbol]):
            if old<start and old+60<=now:
                closed=self.pending[symbol].pop(old)
                self.history(symbol,closed,now)
        if end>now:
            self.pending[symbol][start]=SimpleNamespace(date=str(start),open=values[0],high=values[1],low=values[2],close=values[3],volume=float(raw.volume))
            return False
        # A final historicalDataUpdate supersedes its cached partial version.
        # Otherwise arrival of the next minute can resurrect the stale partial.
        self.pending[symbol].pop(start,None)
        self.bars[symbol][start]=Bar(symbol,60,datetime.fromtimestamp(start,timezone.utc),datetime.fromtimestamp(end,timezone.utc),*values,float(raw.volume))
        keys=sorted(self.bars[symbol])
        for key in keys[:-120]:del self.bars[symbol][key]
        return True

    def evaluate_catalog(self, fields_by_symbol, snapshot, positions, now):
        """Retain every catalog strategy, explicit missing configs, no order transport."""
        inputs={}
        for symbol,buckets in self.bars.items():
            q=fields_by_symbol.get(symbol,{})
            bars=[buckets[k] for k in sorted(buckets)]
            if bars and 0<=now-bars[-1].ended_at.timestamp()<=65 and symbol in self.history_complete:
                inputs[symbol]=MarketData(symbol,[b.close for b in bars],datetime.fromtimestamp(now,timezone.utc),q.get('bid'),q.get('ask'))
        self.catalog_report=self.scheduler.run(str(now),inputs,snapshot.get('symbol_health',{}),
            PortfolioState(cash=0,equity=0,positions=positions) if snapshot['reconciliation_complete'] else None,
            global_data_fault=None if snapshot['reconciliation_complete'] else 'BROKER_RECONCILIATION_REQUIRED',
            pause_state=snapshot.get('pause_scopes'))
        self.catalog_report['portfolio_scope']='BROKER_POSITION_QUANTITIES_ONLY; no strategy ownership assumed'
        self.catalog_report['execution_gates_unchanged']=True
        return self.catalog_report

    def history_gaps(self, symbol, now, *, horizon=1800):
        """Missing completed minute starts inside the existing history window."""
        keys=sorted(k for k in self.bars[symbol] if now-horizon <= k and k+60 <= now)
        if not keys:
            return []
        return [k for k in range(keys[0],keys[-1]+60,60) if k not in self.bars[symbol]]

    def evaluate(self, symbol, fields, snapshot, now):
        bars=[self.bars[symbol][k] for k in sorted(self.bars[symbol])]
        health=snapshot.get('symbol_health',{}).get(symbol) or classify_symbol(fields,now,session=session_for_symbol(now))
        reason=None if health['allows_realtime'] else health['reason']
        if symbol not in self.history_complete or len(bars)<self.config.slow_window:
            reason='Historical K-line readback/warmup incomplete'
        recent=bars[-self.config.slow_window:]
        if recent and (any((b.ended_at-a.ended_at).total_seconds()!=60 for a,b in zip(recent,recent[1:]))
                       or not 0<=now-recent[-1].ended_at.timestamp()<=65):
            reason='K-line history stale, future or discontinuous'
        try:
            bid,ask=float(fields['bid']),float(fields['ask'])
            at=min(fields['bid_at'],fields['ask_at'])
            if not (0<bid<=ask and fields.get('data_type')==1 and 0<=now-at<=5):
                reason='Fresh uncrossed live bid and ask required'
        except (KeyError,TypeError,ValueError):
            bid=ask=0;at=now;reason='Live bid/ask unavailable'
        signal=None;proposal=None;decision=None;risk=None
        if reason is None:
            quote=Quote(symbol,(bid+ask)/2,datetime.fromtimestamp(at,timezone.utc),'IBKR live midpoint',bid,ask)
            decision=self.module.evaluate(symbol=symbol,quote=quote,bars=bars,step=int(now//60))
            signal=asdict(decision)
            if decision.is_order and decision.side=='BUY':
                # Existing long stop formula, referenced to proposed entry limit.
                # Actual fill-relative protection still needs broker acceptance.
                stop=normalize_order_price(symbol=symbol,side='SELL',order_type='STP',price=decision.limit_price*(1-self.config.stop_loss_pct),log=False)
                p=TradeProposal(symbol,'BUY',decision.quantity,decision.limit_price,stop)
                risk=asdict(self.risk.validate(p))
                proposal=dict(parent=dict(side='BUY',quantity=p.quantity,order_type='LMT',tif='DAY',limit_price=p.limit_price),
                              child=dict(side='SELL',quantity=p.quantity,order_type='STP',tif='GTC',stop_price=stop),
                              existing_execution_path='TradingService.submit -> TwsPaperBroker.submit_bracket',
                              entry_reference='proposed limit; actual partial-fill coverage NOT assumed')
        local=datetime.fromtimestamp(now,ZoneInfo('America/New_York'))
        regular=local.weekday()<5 and (9,30)<=(local.hour,local.minute)<(16,0)
        report=dict(symbol=symbol,observed_at=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                    status='BLOCKED' if reason else 'EVALUATED',reason=reason,history_bars=len(bars),
                    market_data_health=health,signal_only=True,
                    latest_completed_bar=bars[-1].ended_at.isoformat() if bars else None,
                    completed_bar_ends=[b.ended_at.timestamp() for b in bars],
                    history_gaps=self.history_gaps(symbol,now),
                    strategy_configuration=asdict(self.config),signal=signal,risk_engine=risk,
                    proposed_native_protection=proposal,session_regular=regular,
                    safety_entries_ready=snapshot['entries_ready'],execution_pause=snapshot.get('pause_scopes',{}).get('decisions',{}).get(self.module.name,{}).get(symbol),transmit=False,
                    eligible_to_submit=False,approval_required=True,mode='MONITOR_ONLY',
                    remaining_gates=['Formal execution approval','Broker-native partial-fill acceptance',
                                     'Portfolio exposure including external holdings','Fees/FX allowance within 200 USD'])
        self.last_report[symbol]=report
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(mode='MONITOR_ONLY',transmit=False,symbols=self.last_report,catalog=self.catalog_report),indent=2))
        temporary.chmod(0o600);temporary.replace(self.path)
        return report
