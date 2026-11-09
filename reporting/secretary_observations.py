"""Bounded observations for the already running secretary input owner."""
from .gateway_session_events import collect
from .incidents import IncidentStore
from .market_subscriptions import check
from .market_clock import collect as market_clock
from .engineering_weekly import collect as engineering_weekly
from .recovery import RecoveryCoordinator
from .market_clock import load_calendar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def observe(archive, root):
    results = {}; errors = {}
    jobs = {'gateway_sessions': lambda: collect(IncidentStore(root/'runtime/recovery.sqlite3'), root),
            'market_clock': lambda: market_clock(IncidentStore(root/'runtime/recovery.sqlite3')),
            'engineering_weekly': lambda: engineering_weekly(archive, IncidentStore(root/'runtime/recovery.sqlite3')),
            'market_subscription_sample': lambda: check(archive, root, periodic=True)}
    for name, run in jobs.items():
        try:
            result = run()
            results[name] = result if isinstance(result, int) else 'RECORDED' if result else 'NOT_DUE'
        except Exception as exc:
            errors[name] = type(exc).__name__
    coordinator = RecoveryCoordinator(root/'runtime/recovery.sqlite3')
    for job,module in (('market_clock','MARKET_CLOCK'),('engineering_weekly','ENGINEERING_WEEKLY')):
        failed = job in errors
        expired = False
        if job=='market_clock' and not failed:
            data=load_calendar();now=datetime.now(timezone.utc)
            expired=any(not data['valid_from']<=now.astimezone(ZoneInfo(p['timezone'])).date().isoformat()<=min(data['valid_through'],p.get('valid_through',data['valid_through'])) for p in data['profiles'].values())
        coordinator.observe(module,'DEGRADED' if failed or expired else 'HEALTHY',freshness='FRESH',enabled=True,reason=errors.get(job) or ('Calendar coverage expired' if expired else 'Bounded notification producer checked; delivery and trading independent'))
    return dict(observations=results, errors=errors, grants_trading_permission=False)
