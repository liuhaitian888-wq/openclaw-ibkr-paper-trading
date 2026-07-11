#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_SHARED_DIR="$HOME/Documents/openclaw_shared"
if [[ ! -d "$DEFAULT_SHARED_DIR" && -d "/Volumes/openclaw_shared" ]]; then
  DEFAULT_SHARED_DIR="/Volumes/openclaw_shared"
fi
SHARED_DIR="${OPENCLAW_SHARED_DIR:-$DEFAULT_SHARED_DIR}"
TOKEN_FILE="$SHARED_DIR/trade_session_token"
RUNTIME_DIR="$PROJECT_DIR/.runtime"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$RUNTIME_DIR/trading_api.pid"
POOL_PID_FILE="$RUNTIME_DIR/pool_strategy.pid"
AGENT_PID_FILE="$RUNTIME_DIR/autonomous_agent.pid"
API_LOG_FILE="$LOG_DIR/trading_api.log"
POOL_LOG_FILE="$LOG_DIR/pool_strategy.log"
AGENT_LOG_FILE="$LOG_DIR/autonomous_agent.log"
DEFAULT_UNIVERSE_FILE="$PROJECT_DIR/data/us_equity_universe.csv"
VM_HOST="${OPENCLAW_VM_HOST:-192.168.64.2}"
VM_USER="${OPENCLAW_VM_USER:-nbhsbgnb}"
VM_KEY="${OPENCLAW_VM_KEY:-$HOME/.ssh/openclaw_vm_ed25519}"
VM_TOKEN_FILE="${OPENCLAW_VM_TOKEN_FILE:-/mnt/openclaw_shared/trade_session_token}"

cd "$PROJECT_DIR"

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5)
if [[ -f "$VM_KEY" ]]; then
  SSH_OPTS+=(-i "$VM_KEY")
fi

vm_ssh_ready() {
  ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" 'true' >/dev/null 2>&1
}

write_trade_token_file() {
  local token="$1"

  if [[ -d "$SHARED_DIR" ]]; then
    printf '%s\n' "$token" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE" 2>/dev/null || true
    echo "Shared token file written: $TOKEN_FILE"
    return 0
  fi

  if vm_ssh_ready; then
    printf '%s\n' "$token" | ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" \
      "umask 177; cat > '$VM_TOKEN_FILE'"
    echo "Shared token file written through SSH: $VM_USER@$VM_HOST:$VM_TOKEN_FILE"
    return 0
  fi

  echo "Shared folder not mounted at $SHARED_DIR, and SSH is not reachable for $VM_USER@$VM_HOST."
  echo "Mount/open the shared folder or fix SSH, then run this script again."
  return 1
}

clear_trade_token_file() {
  if [[ -f "$TOKEN_FILE" ]]; then
    : > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE" 2>/dev/null || true
    echo "Cleared shared token file: $TOKEN_FILE"
    return 0
  fi

  if [[ -d "$SHARED_DIR" ]]; then
    : > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE" 2>/dev/null || true
    echo "Created empty shared token file: $TOKEN_FILE"
    return 0
  fi

  if vm_ssh_ready; then
    ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" \
      "umask 177; : > '$VM_TOKEN_FILE'"
    echo "Cleared shared token file through SSH: $VM_USER@$VM_HOST:$VM_TOKEN_FILE"
    return 0
  fi

  echo "Shared folder not mounted at $SHARED_DIR, and SSH is not reachable; no token file changed."
  return 0
}

stop_api_if_running() {
  if pgrep -f "api_service.py" >/dev/null 2>&1; then
    pkill -f "api_service.py" || true
    sleep 1
    echo "Stopped existing api_service.py process before switching mode."
  fi
}

stop_pool_strategy_if_running() {
  if [[ -f "$POOL_PID_FILE" ]]; then
    local pid
    pid="$(cat "$POOL_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" || true
      sleep 1
      echo "Stopped existing pool strategy process: $pid"
    fi
    : > "$POOL_PID_FILE"
  fi
  if pgrep -f "scripts/run_pool_strategy_module.py" >/dev/null 2>&1; then
    pkill -f "scripts/run_pool_strategy_module.py" || true
    sleep 1
    echo "Stopped remaining pool strategy processes."
  fi
}

stop_autonomous_agent_if_running() {
  if [[ -f "$AGENT_PID_FILE" ]]; then
    local pid
    pid="$(cat "$AGENT_PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" || true
      sleep 1
      echo "Stopped existing autonomous agent process: $pid"
    fi
    : > "$AGENT_PID_FILE"
  fi
  if pgrep -f "scripts/run_autonomous_trading_agent.py" >/dev/null 2>&1; then
    pkill -f "scripts/run_autonomous_trading_agent.py" || true
    sleep 1
    echo "Stopped remaining autonomous agent processes."
  fi
}

default_universe_symbols() {
  .venv313/bin/python -c 'from trading.universe import default_universe_symbols, symbols_csv; print(symbols_csv(default_universe_symbols()))'
}

api_health_ok() {
  local url="$1"
  local key="$2"
  curl -fsS --max-time 2 -H "X-API-Key: $key" "$url/health" >/dev/null 2>&1
}

detect_api_url() {
  local key="$1"
  local candidate
  local candidates=()

  if [[ -n "${TRADING_API_URL:-}" ]]; then
    candidates+=("${TRADING_API_URL%/}")
  fi
  candidates+=(
    "http://192.168.64.1:8787"
    "http://127.0.0.1:8787"
    "http://localhost:8787"
  )

  for candidate in "${candidates[@]}"; do
    if api_health_ok "$candidate" "$key"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

load_trade_token_env() {
  if [[ -n "${TRADE_SESSION_TOKEN:-}" ]]; then
    return 0
  fi

  if [[ -s "$TOKEN_FILE" ]]; then
    TRADE_SESSION_TOKEN="$(cat "$TOKEN_FILE")"
    export TRADE_SESSION_TOKEN
    return 0
  fi

  if vm_ssh_ready; then
    TRADE_SESSION_TOKEN="$(
      ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" \
        "test -s '$VM_TOKEN_FILE' && cat '$VM_TOKEN_FILE' || true"
    )"
    if [[ -n "$TRADE_SESSION_TOKEN" ]]; then
      export TRADE_SESSION_TOKEN
      return 0
    fi
  fi

  echo "TRADE_SESSION_TOKEN is not available in env, $TOKEN_FILE, or $VM_USER@$VM_HOST:$VM_TOKEN_FILE."
  return 1
}

run_gateway_health() {
  local key
  local url
  key="$(cat .secrets/openclaw_api_key)"
  if ! url="$(detect_api_url "$key")"; then
    echo "No running Trading API found."
    echo "Start TRADE_LOCK first, then choose background mode if you want this menu back."
    echo "Tried: ${TRADING_API_URL:-http://192.168.64.1:8787}, http://127.0.0.1:8787, http://localhost:8787"
    return 1
  fi
  echo "Trading API: $url"
  curl -fsS -H "X-API-Key: $key" "$url/health"
  echo
}

run_auto_sequence() {
  local mode="$1"
  local mode_label
  local key
  local url
  mode_label="$(printf '%s' "$mode" | tr '[:lower:]' '[:upper:]')"
  if [[ "$mode" == "paper" ]]; then
    load_trade_token_env
  fi
  key="$(cat .secrets/openclaw_api_key)"
  if ! url="$(detect_api_url "$key")"; then
    echo "No running Trading API found for AUTO_${mode_label}_SEQ."
    echo "Choose 2) TRADE_LOCK and run the API in background, then rerun this option."
    return 1
  fi
  echo "Trading API: $url"
  .venv313/bin/python scripts/run_auto_order_sequence.py \
    --mode "$mode" \
    --symbols "${AUTO_SEQUENCE_SYMBOLS:-AAPL,MSFT,SPY}" \
    --max-orders "${AUTO_SEQUENCE_MAX_ORDERS:-3}" \
    --api-url "$url" \
    --market-data-type "${AUTO_SEQUENCE_MARKET_DATA_TYPE:-3}" \
    --exchange "${AUTO_SEQUENCE_EXCHANGE:-SMART}" \
    --quote-timeout "${AUTO_SEQUENCE_QUOTE_TIMEOUT:-8}" \
    --api-timeout "${AUTO_SEQUENCE_API_TIMEOUT:-30}"
}

run_pool_strategy_module() {
  local mode="${1:-${POOL_STRATEGY_MODE:-paper}}"
  local mode_label
  local key
  local url
  mode_label="$(printf '%s' "$mode" | tr '[:lower:]' '[:upper:]')"
  if [[ "$mode" == "paper" ]]; then
    load_trade_token_env
  fi
  key="$(cat .secrets/openclaw_api_key)"
  if ! url="$(detect_api_url "$key")"; then
    echo "No running Trading API found for POOL_STRATEGY_${mode_label}."
    echo "Choose 2) TRADE_LOCK and run the API in background, then rerun this option."
    return 1
  fi
  echo "Trading API: $url"
  .venv313/bin/python scripts/run_pool_strategy_module.py \
    --mode "$mode" \
    --source "${POOL_STRATEGY_SOURCE:-ibkr-readonly}" \
    --universe-file "${POOL_STRATEGY_UNIVERSE_FILE:-$DEFAULT_UNIVERSE_FILE}" \
    --symbols "${POOL_STRATEGY_SYMBOLS:-}" \
    --max-universe-symbols "${POOL_STRATEGY_MAX_UNIVERSE_SYMBOLS:-60}" \
    --min-value-score "${POOL_STRATEGY_MIN_VALUE_SCORE:-45}" \
    --steps "${POOL_STRATEGY_STEPS:-24}" \
    --batch-size "${POOL_STRATEGY_BATCH_SIZE:-12}" \
    ${POOL_STRATEGY_FULL_POOL_EACH_STEP:+--full-pool-each-step} \
    --max-orders "${POOL_STRATEGY_MAX_ORDERS:-4}" \
    --api-url "$url" \
    --market-data-type "${POOL_STRATEGY_MARKET_DATA_TYPE:-1}" \
    --exchange "${POOL_STRATEGY_EXCHANGE:-SMART}" \
    --ibkr-workers "${POOL_STRATEGY_IBKR_WORKERS:-3}" \
    --ibkr-symbols-per-worker "${POOL_STRATEGY_IBKR_SYMBOLS_PER_WORKER:-6}" \
    --quote-timeout "${POOL_STRATEGY_QUOTE_TIMEOUT:-8}" \
    --api-timeout "${POOL_STRATEGY_API_TIMEOUT:-30}"
}

start_pool_strategy_background() {
  local key
  local url
  load_trade_token_env
  key="$(cat .secrets/openclaw_api_key)"
  if ! url="$(detect_api_url "$key")"; then
    echo "No running Trading API found for background pool strategy."
    echo "Choose 2) TRADE_LOCK background first, then choose this option."
    return 1
  fi
  mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
  stop_pool_strategy_if_running
  nohup .venv313/bin/python scripts/run_pool_strategy_module.py \
    --mode "${POOL_STRATEGY_MODE:-paper}" \
    --source "${POOL_STRATEGY_SOURCE:-ibkr-readonly}" \
    --universe-file "${POOL_STRATEGY_UNIVERSE_FILE:-$DEFAULT_UNIVERSE_FILE}" \
    --symbols "${POOL_STRATEGY_SYMBOLS:-}" \
    --max-universe-symbols "${POOL_STRATEGY_MAX_UNIVERSE_SYMBOLS:-60}" \
    --min-value-score "${POOL_STRATEGY_MIN_VALUE_SCORE:-45}" \
    --steps "${POOL_STRATEGY_STEPS:-390}" \
    --batch-size "${POOL_STRATEGY_BATCH_SIZE:-12}" \
    --full-pool-each-step \
    --poll-seconds "${POOL_STRATEGY_POLL_SECONDS:-60}" \
    --max-orders "${POOL_STRATEGY_MAX_ORDERS:-4}" \
    --api-url "$url" \
    --market-data-type "${POOL_STRATEGY_MARKET_DATA_TYPE:-1}" \
    --exchange "${POOL_STRATEGY_EXCHANGE:-SMART}" \
    --ibkr-workers "${POOL_STRATEGY_IBKR_WORKERS:-3}" \
    --ibkr-symbols-per-worker "${POOL_STRATEGY_IBKR_SYMBOLS_PER_WORKER:-6}" \
    --quote-timeout "${POOL_STRATEGY_QUOTE_TIMEOUT:-8}" \
    --api-timeout "${POOL_STRATEGY_API_TIMEOUT:-30}" \
    >> "$POOL_LOG_FILE" 2>&1 &
  local pid="$!"
  printf '%s\n' "$pid" > "$POOL_PID_FILE"
  echo "Started pool strategy in background."
  echo "PID: $pid"
  echo "Log: $POOL_LOG_FILE"
}

start_autonomous_agent_background() {
  local key
  local url
  load_trade_token_env
  key="$(cat .secrets/openclaw_api_key)"
  if ! url="$(detect_api_url "$key")"; then
    echo "No running Trading API found for autonomous agent."
    echo "Choose 2) TRADE_LOCK background first, then choose this option."
    return 1
  fi
  mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
  launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.openclaw.autonomous-paper.plist" >/dev/null 2>&1 || true
  stop_autonomous_agent_if_running
  MODE9_BUY_FREEZE="${MODE9_BUY_FREEZE:-true}" nohup .venv313/bin/python scripts/run_autonomous_trading_agent.py \
    --api-url "$url" \
    --universe-file "${AGENT_UNIVERSE_FILE:-$DEFAULT_UNIVERSE_FILE}" \
    --max-universe-symbols "${AGENT_MAX_UNIVERSE_SYMBOLS:-60}" \
    --min-value-score "${AGENT_MIN_VALUE_SCORE:-45}" \
    --cycle-seconds "${AGENT_CYCLE_SECONDS:-30}" \
    --strategy-every-cycles "${AGENT_STRATEGY_EVERY_CYCLES:-2}" \
    --strategy-mode "${AGENT_STRATEGY_MODE:-paper}" \
    --strategy-steps "${AGENT_STRATEGY_STEPS:-1}" \
    --strategy-max-orders "${AGENT_STRATEGY_MAX_ORDERS:-4}" \
    --ibkr-workers "${AGENT_IBKR_WORKERS:-8}" \
    --ibkr-symbols-per-worker "${AGENT_IBKR_SYMBOLS_PER_WORKER:-8}" \
    --quote-timeout "${AGENT_QUOTE_TIMEOUT:-8}" \
    --market-data-type "${AGENT_MARKET_DATA_TYPE:-1}" \
    ${AGENT_AUTO_APPROVE_CANDIDATES:+--candidate-auto-approve} \
    >> "$AGENT_LOG_FILE" 2>&1 &
  local pid="$!"
  printf '%s\n' "$pid" > "$AGENT_PID_FILE"
  echo "Started autonomous agent in background."
  echo "PID: $pid"
  echo "Log: $AGENT_LOG_FILE"
  echo "Latest state: $PROJECT_DIR/reports/autonomous_agent/latest.json"
}

set_dev_lock_env() {
  export TRADING_API_HOST=192.168.64.1
  export TRADING_API_PORT=8787
  export TRADING_MODE=PAPER
  export ALLOW_TWS_STAGING=true
  export ALLOW_PAPER_TRANSMIT=false
  export ALLOW_OUTSIDE_RTH=false
  export TRADING_KILL_SWITCH=true
  export ALLOWED_SYMBOLS="${ALLOWED_SYMBOLS:-$(default_universe_symbols)}"
  export MAX_ORDER_VALUE=200
  export MAX_QUANTITY=1
  export MAX_RISK_PER_ORDER=10
}

set_trade_lock_env() {
  export TRADING_API_HOST=192.168.64.1
  export TRADING_API_PORT=8787
  export TRADING_MODE=PAPER
  export ALLOW_TWS_STAGING=true
  export ALLOW_PAPER_TRANSMIT=true
  export ALLOW_OUTSIDE_RTH=true
  export TRADING_KILL_SWITCH=false
  export ALLOWED_SYMBOLS="${ALLOWED_SYMBOLS:-$(default_universe_symbols)}"
  export MAX_ORDER_VALUE=400
  export MAX_QUANTITY=1
  export MAX_RISK_PER_ORDER=10
}

start_api_background() {
  mkdir -p "$RUNTIME_DIR" "$LOG_DIR"
  stop_api_if_running
  nohup .venv313/bin/python api_service.py >> "$API_LOG_FILE" 2>&1 &
  local pid="$!"
  printf '%s\n' "$pid" > "$PID_FILE"
  sleep 1

  echo "Started Trading API in background."
  echo "PID: $pid"
  echo "Log: $API_LOG_FILE"
  echo "API URL: http://$TRADING_API_HOST:$TRADING_API_PORT"
  echo "To stop cleanly, rerun this menu and choose 0) STOP."
}

run_monitor_on() {
  export MODE9_MONITORING_LINE_ENABLED=true
  export ACCOUNT_STATE_MANAGER_ENABLED=true
  export ACCOUNT_STATE_MANAGER_CONNECTED_TO_MODE9=true
  export POOL_MANAGER_CONNECTED_TO_MODE9=true
  export POOL_MANAGER_REPORT_ONLY=true
  export EVENT_ROUTER_REPORT_ONLY=true
  export SIX_LAYER_POOLS_EXECUTION_ACTIVE=false
  export TRADE_POOL_BUY_EXECUTION_ENABLED=false
  export TRADING_MODE=PAPER
  export MODE9_BUY_FREEZE=true
  export LIVE_TRADING_ENABLED=false
  export ALLOW_OPTIONS_EXECUTION=false
  export ALLOW_MARKET_ORDERS=false
  export NO_PAID_MARKET_DATA_REQUESTS=true
  export ALLOW_REGULATORY_SNAPSHOT=false
  export ALLOW_SNAPSHOT_MARKET_DATA=false
  export ALLOW_DELAYED_DATA_FOR_EXECUTION=false
  export ALLOW_DELAYED_DATA_FOR_REPORTS=true
  export MARKET_DATA_EXECUTION_REQUIRES_LIVE=true
  .venv313/bin/python scripts/run_mode9_report_only_infrastructure_cycle.py
  echo "Monitoring line is ON in report-only mode."
  echo "BUY freeze remains true; live trading remains false; trade-pool execution remains inactive."
}

run_monitor_off() {
  export MODE9_MONITORING_LINE_ENABLED=false
  export ACCOUNT_STATE_MANAGER_ENABLED=false
  export ACCOUNT_STATE_MANAGER_CONNECTED_TO_MODE9=false
  export POOL_MANAGER_REPORT_ONLY=true
  export EVENT_ROUTER_REPORT_ONLY=true
  export SIX_LAYER_POOLS_EXECUTION_ACTIVE=false
  export TRADE_POOL_BUY_EXECUTION_ENABLED=false
  export TRADING_MODE=PAPER
  export MODE9_BUY_FREEZE=true
  export LIVE_TRADING_ENABLED=false
  export ALLOW_OPTIONS_EXECUTION=false
  export ALLOW_MARKET_ORDERS=false
  export NO_PAID_MARKET_DATA_REQUESTS=true
  export ALLOW_REGULATORY_SNAPSHOT=false
  export ALLOW_SNAPSHOT_MARKET_DATA=false
  .venv313/bin/python - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path.cwd()
payload = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "source": "monitoring_line",
    "mode9_monitoring_line_enabled": False,
    "account_state_manager_enabled": False,
    "account_state_manager_connected_to_mode9": False,
    "pool_manager_report_only": True,
    "event_router_report_only": True,
    "six_layer_pools_execution_active": False,
    "trade_pool_buy_execution_enabled": False,
    "mode9_buy_freeze": True,
    "live_trading_enabled": False,
    "allow_options_execution": False,
    "allow_market_orders": False,
    "orders_submitted": 0,
}
directory = root / "reports" / "monitoring_line"
directory.mkdir(parents=True, exist_ok=True)
(directory / "latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
(directory / "latest.md").write_text("# Monitoring Line\n\n- mode9_monitoring_line_enabled: False\n- mode9_buy_freeze: True\n- live_trading_enabled: False\n- six_layer_pools_execution_active: False\n- orders_submitted: 0\n", encoding="utf-8")
print(json.dumps({"status": "ok", "report": str(directory / "latest.json")}, indent=2))
PY
  echo "Monitoring line is OFF. Safety locks remain conservative."
}

run_monitor_status() {
  if [[ -f "$PROJECT_DIR/reports/monitoring_line/latest.json" ]]; then
    cat "$PROJECT_DIR/reports/monitoring_line/latest.json"
    echo
  else
    echo "No monitoring line report found."
    return 1
  fi
}

set_safe_report_env() {
  export TRADING_MODE=PAPER
  export MODE9_BUY_FREEZE=true
  export LIVE_TRADING_ENABLED=false
  export ALLOW_OPTIONS_EXECUTION=false
  export ALLOW_MARKET_ORDERS=false
  export NO_PAID_MARKET_DATA_REQUESTS=true
  export ALLOW_REGULATORY_SNAPSHOT=false
  export ALLOW_SNAPSHOT_MARKET_DATA=false
  export ALLOW_DELAYED_DATA_FOR_EXECUTION=false
  export MARKET_DATA_EXECUTION_REQUIRES_LIVE=true
  export POSITION_PROTECTION_REPAIR_ENABLED=false
  export GAP_ESCAPE_EXECUTION_ENABLED=false
  export TRADE_POOL_BUY_EXECUTION_ENABLED=false
  export SIX_LAYER_POOLS_EXECUTION_ACTIVE=false
}

run_market_session() {
  set_safe_report_env
  .venv313/bin/python - <<'PY'
from trading.market_session import write_market_session_report

payload = write_market_session_report()
print(open("reports/market_session/latest.md", encoding="utf-8").read())
PY
}

run_rollout_precheck() {
  set_safe_report_env
  .venv313/bin/python - <<'PY'
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.run_full_paper_rollout import current_position_and_open_order_symbols, market_session_blocks_quote_wait
from trading.config import Settings
from trading.market_session import fetch_ibkr_contract_details, write_market_session_report
from trading.process_guard import current_execution_processes, read_lock

root = Path.cwd()
settings = Settings.load()
symbols = current_position_and_open_order_symbols(settings)
contract_details = fetch_ibkr_contract_details(
    symbols,
    host=settings.tws_host,
    port=settings.tws_port,
    client_id=settings.tws_client_id + 1966,
    timeout=float(os.getenv("MARKET_SESSION_CONTRACT_DETAILS_TIMEOUT", "4.0")),
)
market_session = write_market_session_report(symbols=symbols, contract_details=contract_details)
processes = current_execution_processes()
lock_owner = read_lock()
blocks_quote_wait = market_session_blocks_quote_wait(market_session)
payload = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "source": "rollout_precheck",
    "mode9_market_session": market_session,
    "market_session_allows_quote_wait": not blocks_quote_wait,
    "expected_live_bid_ask": market_session.get("expected_live_bid_ask"),
    "live_trading_enabled": os.getenv("LIVE_TRADING_ENABLED") == "true",
    "buy_freeze": os.getenv("MODE9_BUY_FREEZE") == "true",
    "regulatory_snapshot_allowed": os.getenv("ALLOW_REGULATORY_SNAPSHOT") == "true",
    "snapshot_market_data_allowed": os.getenv("ALLOW_SNAPSHOT_MARKET_DATA") == "true",
    "paid_market_data_requests_blocked": os.getenv("NO_PAID_MARKET_DATA_REQUESTS") == "true",
    "active_execution_processes": [proc.__dict__ | {"process_name": proc.process_name} for proc in processes],
    "lock_owner": lock_owner,
    "rollout_should_continue_to_quote_acquisition": not blocks_quote_wait,
    "blocked_reason": market_session.get("blocked_reason") if blocks_quote_wait else "",
    "orders_submitted": 0,
    "orders_cancelled": 0,
}
directory = root / "reports" / "full_paper_rollout"
directory.mkdir(parents=True, exist_ok=True)
(directory / "rollout_precheck.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
(directory / "rollout_precheck.md").write_text(
    "\n".join([
        "# Rollout Precheck",
        "",
        f"- timestamp: {payload['timestamp']}",
        f"- session_state: {market_session.get('session_state')}",
        f"- expected_live_bid_ask: {payload['expected_live_bid_ask']}",
        f"- rollout_should_continue_to_quote_acquisition: {payload['rollout_should_continue_to_quote_acquisition']}",
        f"- blocked_reason: {payload['blocked_reason']}",
        f"- live_trading_enabled: {payload['live_trading_enabled']}",
        f"- buy_freeze: {payload['buy_freeze']}",
        f"- regulatory_snapshot_allowed: {payload['regulatory_snapshot_allowed']}",
        f"- snapshot_market_data_allowed: {payload['snapshot_market_data_allowed']}",
        f"- paid_market_data_requests_blocked: {payload['paid_market_data_requests_blocked']}",
        "- orders_submitted: 0",
        "- orders_cancelled: 0",
        "",
    ]),
    encoding="utf-8",
)
print(json.dumps({
    "session_state": market_session.get("session_state"),
    "expected_live_bid_ask": payload["expected_live_bid_ask"],
    "rollout_should_continue_to_quote_acquisition": payload["rollout_should_continue_to_quote_acquisition"],
    "blocked_reason": payload["blocked_reason"],
    "report": "reports/full_paper_rollout/rollout_precheck.json",
}, indent=2))
PY
}

if [[ ! -x ".venv313/bin/python" ]]; then
  echo "Python venv missing: $PROJECT_DIR/.venv313/bin/python"
  exit 1
fi

if [[ ! -f ".secrets/openclaw_api_key" ]]; then
  echo "Missing API key file: $PROJECT_DIR/.secrets/openclaw_api_key"
  exit 1
fi

DAILY_TOKEN="$(
  .venv313/bin/python - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"

if [[ $# -gt 0 ]]; then
  choice="$1"
else
  echo "Trading Gateway Mode Control"
echo
echo "A fresh daily TRADE_SESSION_TOKEN has been generated."
echo "It will only be written to the shared folder if you choose TRADE_LOCK."
echo
echo "0) STOP       - stop Mac API and clear shared trade token"
echo "1) DEV_LOCK   - code edits allowed, trading blocked"
echo "2) TRADE_LOCK - paper trading allowed, choose foreground or background API"
echo
echo "Checks / TRADE_LOCK automation against the currently running API:"
echo "3) HEALTH              - check Mac Python API and TWS readiness"
echo "4) AUTO_VALIDATE_SEQ   - requires TRADE_LOCK; validate automatic order sequence"
echo "5) AUTO_STAGE_SEQ      - DANGEROUS manual-transmit test; intentionally creates NEW untransmitted TWS orders"
echo "6) AUTO_PAPER_SEQ      - requires TRADE_LOCK; create NEW transmitted paper orders"
echo "7) POOL_STRATEGY_PAPER - run classic conservative pool module automatically"
echo "8) POOL_STRATEGY_BG    - start long paper pool strategy in background"
echo "9) AUTONOMOUS_AGENT_BG - AI supervisor: research tasks + full-pool strategy"
echo "10) MONITOR_ON         - enable report-only monitoring line and account state manager"
echo "11) MARKET_SESSION     - report current US equity market session"
echo "12) ROLLOUT_PRECHECK   - safe report-only precheck before full paper rollout"
echo
read -r -p "Choose mode [0/1/2/3/4/5/6/7/8/9/10/11/12]: " choice
fi

case "$choice" in
  0|STOP|stop)
    unset TRADE_SESSION_TOKEN
    unset TRADE_SESSION_TOKEN_FILE
    clear_trade_token_file

    stop_pool_strategy_if_running
    stop_autonomous_agent_if_running
    stop_api_if_running
    echo "STOP complete."
    exit 0
    ;;

  1|DEV|dev|DEV_LOCK|dev_lock)
    unset TRADE_SESSION_TOKEN
    unset TRADE_SESSION_TOKEN_FILE
    clear_trade_token_file
    stop_pool_strategy_if_running
    stop_autonomous_agent_if_running
    stop_api_if_running

    set_dev_lock_env

    echo
    echo "Starting Mac Python API in DEV_LOCK."
    echo "Trading kill switch: true"
    echo "Paper transmit: false"
    echo "Trade session token: unset"
    ;;

  2|TRADE|trade|TRADE_LOCK|trade_lock)
    write_trade_token_file "$DAILY_TOKEN"
    export TRADE_SESSION_TOKEN="$DAILY_TOKEN"
    unset TRADE_SESSION_TOKEN_FILE

    set_trade_lock_env

    echo
    echo "Starting Mac Python API in TRADE_LOCK."
    echo "Trading kill switch: false"
    echo "Paper transmit: true"
    echo
    echo "Run API how?"
    echo "f) foreground - keep logs visible here; Ctrl+C stops API"
    echo "b) background - return to shell, then rerun this menu for 3/4/5/6"
    read -r -p "Choose [f/b]: " run_style
    if [[ "$run_style" == "b" || "$run_style" == "B" || "$run_style" == "background" ]]; then
      start_api_background
      exit 0
    fi
    stop_api_if_running
    ;;

  3|HEALTH|health)
    run_gateway_health
    exit 0
    ;;

  4|AUTO_VALIDATE_SEQ|auto_validate_seq|validate-seq|validate_seq)
    run_auto_sequence validate
    exit 0
    ;;

  5|AUTO_STAGE_SEQ|auto_stage_seq|stage-seq|stage_seq)
    echo
    echo "DANGER: AUTO_STAGE_SEQ intentionally creates untransmitted staged orders in TWS."
    echo "These orders may require manual Transmit or manual cancellation in TWS."
    read -r -p "Type STAGE to continue: " stage_confirm
    if [[ "$stage_confirm" != "STAGE" ]]; then
      echo "AUTO_STAGE_SEQ aborted; confirmation did not match STAGE."
      exit 1
    fi
    run_auto_sequence stage
    exit 0
    ;;

  6|AUTO_PAPER_SEQ|auto_paper_seq|paper-seq|paper_seq)
    run_auto_sequence paper
    exit 0
    ;;

  7|POOL_STRATEGY_PAPER|pool_strategy_paper|pool-paper|pool_paper)
    run_pool_strategy_module "${POOL_STRATEGY_MODE:-paper}"
    exit 0
    ;;

  8|POOL_STRATEGY_BG|pool_strategy_bg|pool-bg|pool_bg)
    start_pool_strategy_background
    exit 0
    ;;

  9|AUTONOMOUS_AGENT_BG|autonomous_agent_bg|agent-bg|agent_bg)
    start_autonomous_agent_background
    exit 0
    ;;

  10|MONITOR_ON|monitor-on|monitor_on)
    run_monitor_on
    exit 0
    ;;

  MONITOR_OFF|monitor-off|monitor_off)
    run_monitor_off
    exit 0
    ;;

  STATUS|status)
    run_monitor_status
    exit 0
    ;;

  11|MARKET_SESSION|market-session|market_session)
    run_market_session
    exit 0
    ;;

  12|ROLLOUT_PRECHECK|rollout-precheck|rollout_precheck)
    run_rollout_precheck
    exit 0
    ;;

  *)
    echo "Invalid choice: $choice"
    exit 1
    ;;
esac

echo
echo "API URL: http://$TRADING_API_HOST:$TRADING_API_PORT"
echo "Press Ctrl+C in this terminal to stop the API."
echo

exec .venv313/bin/python api_service.py
