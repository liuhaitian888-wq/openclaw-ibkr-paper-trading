"""One bounded Paper news read; no orders, notifications or background worker."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from trading.news_feed import collect, health_observation
from trading.production_paths import STATE_ROOT
from ops.cloud.monitoring_guard import monitoring_service


def main():
    os.umask(0o077)
    with monitoring_service('ibkr-news-probe', STATE_ROOT):
        config_path = Path.home()/'.config/openclaw/paper-observer.json'
        if config_path.stat().st_mode & 0o077:
            raise PermissionError('Private observer config required')
        with config_path.open() as handle:
            config = json.load(handle)
        from ib_async import IB, Stock
        result = asyncio.run(collect(IB(), Stock, expected_account=config['expected_account']))
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        history = STATE_ROOT/'observations/news'
        history.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (history/(stamp+'.json')).open('x') as handle:
            json.dump(result, handle, indent=2)
        latest = STATE_ROOT/'runtime/news.latest.json'
        temporary = latest.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2))
        temporary.replace(latest)
        # Separate local evidence; the shared resolver evaluates NEWS independently.
        observation = STATE_ROOT/'runtime/news.health.json'
        temporary = observation.with_suffix('.tmp')
        temporary.write_text(json.dumps(health_observation(result), indent=2))
        temporary.replace(observation)
        from reporting.recovery import RecoveryCoordinator
        health = health_observation(result)
        RecoveryCoordinator(STATE_ROOT/'runtime/recovery.sqlite3').observe('NEWS',
            health['state'], freshness=health['freshness'], reason=health['reason'],
            evidence_path=str(latest), broker_completed_at=result['completed_at'])
        print(json.dumps(result, indent=2))
        return 0 if result['news_usable'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
