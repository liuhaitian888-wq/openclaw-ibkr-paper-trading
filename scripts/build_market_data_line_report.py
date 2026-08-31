#!/usr/bin/env python3
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.config import Settings
from trading.market_data_line_manager import MarketDataLineManager


def main() -> int:
    settings = Settings.load()
    latest_agent = _read_json(PROJECT_ROOT / "reports/autonomous_agent/latest.json")
    from scripts.list_tws_orders import read_tws_orders

    orders = read_tws_orders(
        host=settings.tws_host,
        port=settings.tws_port,
        client_id=settings.tws_client_id + 920,
        timeout=settings.tws_status_timeout,
    )
    open_order_symbols = [str(order.get("symbol", "")) for order in orders.get("open_orders", [])]
    core_symbols = list(latest_agent.get("monitor_symbols", []))
    hot_symbols = [str(item.get("symbol", "")) for item in latest_agent.get("top_movers", [])[:5]]
    manager = MarketDataLineManager()
    plan = manager.plan(
        open_order_symbols=open_order_symbols,
        hot_symbols=hot_symbols,
        core_symbols=core_symbols,
    )
    manager.write_report(plan)
    print(json.dumps(plan.__dict__, indent=2, sort_keys=True))
    return 0


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
