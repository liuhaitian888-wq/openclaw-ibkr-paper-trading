"""Signal-only fanout over existing strategy objects. No broker or order service."""
from dataclasses import asdict, dataclass
import hashlib
import json
import threading
from research.strategy_catalog import build_strategy_catalog
from strategies import (DualMovingAverageStrategy, ZScoreMeanReversionStrategy,
                        GridStrategy, LightGbmStyleBaselineStrategy)


@dataclass(frozen=True)
class StrategyBinding:
    name: str
    symbols: tuple
    evaluator: object
    missing_reason: str = ''
    data_dependencies: dict | None = None

    def required_symbols(self, symbol):
        if self.missing_reason:return ()
        return tuple(self.data_dependencies.get(symbol,())) if self.data_dependencies is not None else (symbol,)


def catalog_bindings(configurations, fallback_symbols=()):
    """Preserve catalog and configured universes. Never invent Grid/ML inputs."""
    classes=dict(dual_moving_average=DualMovingAverageStrategy,
                 zscore_mean_reversion=ZScoreMeanReversionStrategy,
                 grid_rebalance=GridStrategy,lightgbm_style_baseline=LightGbmStyleBaselineStrategy)
    bindings=[]
    for entry in build_strategy_catalog().entries:
        cfg=configurations.get(entry.name)
        if cfg is None:
            bindings.append(StrategyBinding(entry.name,tuple(fallback_symbols),None,'STRATEGY_CONFIGURATION_NOT_PROVIDED'))
            continue
        try:
            symbols=tuple(cfg['symbols'])
            if not symbols or any(not isinstance(s,str) or not s for s in symbols) or len(set(symbols))!=len(symbols):
                raise ValueError('Explicit unique strategy universe required')
            dependencies=cfg.get('data_dependencies')
            if dependencies is not None:
                if not isinstance(dependencies,dict) or set(dependencies)!=set(symbols):
                    raise ValueError('Explicit dependency map must cover each traded symbol')
                if any(not isinstance(values,(list,tuple)) for values in dependencies.values()):
                    raise ValueError('Dependency values must be explicit symbol lists')
                dependencies={s:tuple(values) for s,values in dependencies.items()}
                if any(not values or s not in values or len(set(values))!=len(values)
                       or any(not isinstance(v,str) or not v for v in values) for s,values in dependencies.items()):
                    raise ValueError('Invalid strategy market dependencies')
            evaluator=classes[entry.name](**cfg.get('parameters',{}))
            bindings.append(StrategyBinding(entry.name,symbols,evaluator,data_dependencies=dependencies))
        except (TypeError,KeyError,ValueError):
            bindings.append(StrategyBinding(entry.name,tuple(fallback_symbols),None,'CONFIG_MISSING_OR_INVALID'))
    for name in set(configurations)-set(classes):
        cfg=configurations[name]
        symbols=tuple(cfg.get('symbols',fallback_symbols)) if isinstance(cfg,dict) else tuple(fallback_symbols)
        bindings.append(StrategyBinding(name,symbols,None,'STRATEGY_ADAPTER_MISSING'))
    return bindings


def strategy_dependency_registry(configurations, market_symbols):
    """The same declared binding graph for monitor and admission; no worker."""
    bindings=catalog_bindings(configurations or {},market_symbols)
    result={b.name:{s:list(b.required_symbols(s)) for s in b.symbols} for b in bindings}
    result['classic_conservative_trend']={s:[s] for s in market_symbols}
    result['position_protection']={s:[s] for s in market_symbols}
    return result


def dependency_fingerprint(dependencies):
    return hashlib.sha256(json.dumps(dependencies,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class SignalScheduler:
    def __init__(self,bindings):
        self.bindings=tuple(bindings)
        if len({b.name for b in bindings})!=len(bindings):raise ValueError('Duplicate strategy identity')
        self._lock=threading.RLock();self._cache={}

    def run(self,cycle,inputs,health,portfolio,*,global_data_fault=None,pause_state=None):
        """Execution gates deliberately do not stop signal-only scheduling."""
        fingerprint=hashlib.sha256(repr((inputs,health,portfolio,global_data_fault,pause_state)).encode()).hexdigest()
        with self._lock:
            if cycle in self._cache:
                old,result=self._cache[cycle]
                if old!=fingerprint:raise ValueError('Cycle identity reused with conflicting inputs')
                return json.loads(json.dumps(result))
            rows=[]
            for b in self.bindings:
                for symbol in b.symbols:
                    row=dict(strategy=b.name,symbol=symbol,status='SKIPPED',reason=None,signal=None,
                             transmit=False,eligible_to_submit=False,cycle=cycle)
                    h=health.get(symbol,{})
                    reason=global_data_fault or b.missing_reason
                    if not reason and (h.get('status')!='REALTIME_HEALTHY' or h.get('allows_realtime') is not True):
                        reason=h.get('reason','UNKNOWN market data')
                    required=b.required_symbols(symbol)
                    if not reason:
                        for dependency in required:
                            peer=health.get(dependency,{})
                            if peer.get('status')!='REALTIME_HEALTHY' or peer.get('allows_realtime') is not True or dependency not in inputs:
                                reason='STRATEGY_DEPENDENCY_UNAVAILABLE:'+dependency;break
                    if not reason and pause_state is not None:
                        scoped=pause_state.get('decisions',{}).get(b.name,{}).get(symbol,{})
                        row['execution_pause']=scoped
                        if scoped.get('market_allowed') is not True:reason=scoped.get('reason','SCOPED_SAFETY_UNVERIFIED')
                    row['required_symbols']=list(required)
                    if not reason and (symbol not in inputs or portfolio is None):reason='MARKET_OR_PORTFOLIO_INPUT_MISSING'
                    if not reason and b.name=='lightgbm_style_baseline' and 'ml_up_probability' not in inputs[symbol].features:
                        reason='ML_FEATURE_MISSING'
                    if not reason:
                        try:
                            if inputs[symbol].symbol!=symbol:raise ValueError('Market input symbol mismatch')
                            signal=b.evaluator.generate_signal(inputs[symbol],portfolio)
                            if signal.symbol!=symbol:raise ValueError('Strategy result identity mismatch')
                            row.update(status='EVALUATED',signal=asdict(signal))
                            row['signal']['timestamp']=signal.timestamp.isoformat()
                        except Exception as exc:
                            reason='STRATEGY_ERROR_'+type(exc).__name__
                    row['reason']=reason;rows.append(row)
            result=dict(mode='SIGNAL_ONLY',strategies_scheduled=[b.name for b in self.bindings],
                        strategy_states={b.name:dict(state='CONFIG_MISSING' if b.missing_reason else 'SCHEDULED',reason=b.missing_reason,configured_symbols=list(b.symbols) if not b.missing_reason else None) for b in self.bindings},results=rows,
                        execution_enabled=False,pause_scopes=pause_state)
            self._cache[cycle]=(fingerprint,result)
            # Bounded cache; no idempotency claim for orders, which are never sent.
            for old in list(self._cache)[:-2]:del self._cache[old]
            return json.loads(json.dumps(result))
