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
  stop_autonomous_agent_if_running
  nohup .venv313/bin/python scripts/run_autonomous_trading_agent.py \
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
echo "5) AUTO_STAGE_SEQ      - requires TRADE_LOCK; create NEW untransmitted TWS orders"
echo "6) AUTO_PAPER_SEQ      - requires TRADE_LOCK; create NEW transmitted paper orders"
echo "7) POOL_STRATEGY_PAPER - run classic conservative pool module automatically"
echo "8) POOL_STRATEGY_BG    - start long paper pool strategy in background"
echo "9) AUTONOMOUS_AGENT_BG - AI supervisor: research tasks + full-pool strategy"
echo
read -r -p "Choose mode [0/1/2/3/4/5/6/7/8/9]: " choice

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
