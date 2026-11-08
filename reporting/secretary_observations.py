"""Bounded observations for the already running secretary input owner."""
from .gateway_session_events import collect
from .incidents import IncidentStore
from .market_subscriptions import check


def observe(archive, root):
    results = {}; errors = {}
    jobs = {'gateway_sessions': lambda: collect(IncidentStore(root/'runtime/recovery.sqlite3'), root),
            'market_subscription_sample': lambda: check(archive, root, periodic=True)}
    for name, run in jobs.items():
        try:
            result = run()
            results[name] = result if isinstance(result, int) else 'RECORDED' if result else 'NOT_DUE'
        except Exception as exc:
            errors[name] = type(exc).__name__
    return dict(observations=results, errors=errors, grants_trading_permission=False)
