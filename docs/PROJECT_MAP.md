# Project Map

This document is the engineering map for the trading automation project. The
most useful chart types here are:

- C4 model: who owns which boundary.
- Sequence diagram: how a request moves through the system.
- State machine: which lock state allows which action.
- File dependency map: where to look before changing code.

## C4 Container Map

```mermaid
flowchart LR
    USER["Owner / operator"]
    DASH["Dashboard\nscripts/serve_live_dashboard.py\ntrading/dashboard.py"]
    CTRL["Mode control\nscripts/control_trading_mode.command"]
    OC["OpenClaw VM\nopenclaw/openclaw_trading_client.py"]
    DIS["Discord handbook\nmain.py\ndiscord_handbook/"]
    API["Mac Python API\napi_service.py"]
    CORE["Trading core\ntrading/service.py\ntrading/risk.py\ntrading/workflow.py"]
    DATA["Market data adapters\ntrading/ibkr_readonly.py\ntrading/market_data.py"]
    EXEC["TWS paper adapter\ntrading/tws_paper.py"]
    AUDIT["Audit ledger\ntrading/audit.py\ntrading_audit.sqlite3"]
    TWS["IBKR TWS paper\n127.0.0.1:7497"]
    REPORTS["Reports / dashboards\nreports/\ndashboard/"]

    USER --> CTRL
    USER --> DASH
    CTRL --> API
    OC -->|"authenticated proposals only"| API
    DIS -->|"handbook only"| REPORTS
    DASH --> DATA
    DASH --> API
    API --> CORE
    CORE --> DATA
    CORE --> EXEC
    CORE --> AUDIT
    DATA --> TWS
    EXEC --> TWS
    AUDIT --> REPORTS
```

## Order Sequence

```mermaid
sequenceDiagram
    participant User as Owner
    participant Control as control_trading_mode.command
    participant API as api_service.py
    participant Service as trading/service.py
    participant Risk as trading/risk.py
    participant Audit as trading/audit.py
    participant TWS as IBKR TWS Paper

    User->>Control: choose TRADE_LOCK
    Control->>Control: generate TRADE_SESSION_TOKEN
    Control->>API: start Mac Python API
    User->>Control: choose AUTO_VALIDATE/STAGE/PAPER
    Control->>API: GET /health
    API-->>Control: lock, token, TWS readiness
    Control->>API: POST validate/stage/paper limit order
    API->>Service: parse proposal
    Service->>Risk: enforce limits
    Service->>Audit: reserve idempotency key
    alt validate
        Service-->>API: validation result only
    else stage or paper
        Service->>TWS: placeOrder with orderRef=idempotency_key
        TWS-->>Service: order id / status / ack
    end
    Service->>Audit: write status and timings
    API-->>Control: JSON result and report path
```

## Lock State Machine

```mermaid
stateDiagram-v2
    [*] --> STOP
    STOP --> DEV_LOCK: choose 1
    STOP --> TRADE_LOCK: choose 2
    DEV_LOCK --> STOP: choose 0
    TRADE_LOCK --> STOP: choose 0

    STOP: API stopped or token cleared
    DEV_LOCK: validation/research allowed\npaper transmit disabled\nkill switch on
    TRADE_LOCK: paper trading allowed\nrequires daily token\nkill switch off

    DEV_LOCK --> DEV_BLOCKED: stage/paper attempted
    TRADE_LOCK --> VALIDATE: option 4
    TRADE_LOCK --> STAGE: option 5
    TRADE_LOCK --> PAPER: option 6
    VALIDATE --> TRADE_LOCK
    STAGE --> TRADE_LOCK
    PAPER --> TRADE_LOCK
```

## File Map

```mermaid
flowchart TD
    subgraph DOCS["Project docs"]
        README["README.md"]
        ARCH["ARCHITECTURE.md"]
        SEC["SECURITY_MODEL.md"]
        AUD["AUDIT_MODEL.md"]
        DATAFEED["DATA_FEEDS.md"]
        VALUE["VALUE_POOL.md"]
        PMAP["docs/PROJECT_MAP.md"]
    end

    subgraph ENTRY["Entry points"]
        APIENTRY["api_service.py"]
        CTRL["scripts/control_trading_mode.command"]
        LIVE["scripts/start_live_dashboard.command"]
        SEQ["scripts/run_auto_order_sequence.py"]
        SINGLE["scripts/auto_paper_limit_from_quote.py"]
    end

    subgraph TRADING["trading package"]
        CONFIG["trading/config.py"]
        SERVICE["trading/service.py"]
        RISK["trading/risk.py"]
        WORKFLOW["trading/workflow.py"]
        MODELS["trading/models.py"]
        TWS["trading/tws_paper.py"]
        RO["trading/ibkr_readonly.py"]
        MARKET["trading/market_data.py"]
        STRAT["trading/strategy.py"]
        SIM["trading/simulation.py"]
        DASH["trading/dashboard.py"]
        LEDGER["trading/audit.py"]
    end

    subgraph AI["AI and handbook"]
        OC["openclaw/openclaw_trading_client.py"]
        SKILL["openclaw/SKILL.md"]
        DISBOT["discord_handbook/"]
    end

    subgraph OUTPUT["Generated/runtime data"]
        REPORTS["reports/*.json"]
        HTML["dashboard/*.html"]
        DB["trading_audit.sqlite3"]
        LOGS["logs/trading_api.log"]
        RUNTIME[".runtime/trading_api.pid"]
    end

    CTRL --> APIENTRY
    SEQ --> APIENTRY
    SINGLE --> APIENTRY
    LIVE --> DASH
    APIENTRY --> SERVICE
    SERVICE --> CONFIG
    SERVICE --> RISK
    SERVICE --> WORKFLOW
    SERVICE --> MODELS
    SERVICE --> TWS
    SERVICE --> LEDGER
    DASH --> RO
    STRAT --> MARKET
    SIM --> STRAT
    OC --> APIENTRY
    SERVICE --> REPORTS
    DASH --> HTML
    LEDGER --> DB
    CTRL --> LOGS
    CTRL --> RUNTIME
```

## Where To Change Things

Trading safety:

- `trading/risk.py`
- `trading/service.py`
- `trading/config.py`
- `SECURITY_MODEL.md`

IBKR connectivity:

- `trading/tws_paper.py`
- `trading/ibkr_readonly.py`
- `scripts/diagnose_market_data_channels.py`
- `scripts/benchmark_ibkr_quote_batches.py`

Automatic order runs:

- `scripts/control_trading_mode.command`
- `scripts/run_auto_order_sequence.py`
- `scripts/auto_paper_limit_from_quote.py`

Dashboard:

- `scripts/serve_live_dashboard.py`
- `trading/dashboard.py`
- `dashboard/live_strategy_dashboard.html`

Research and strategy modules:

- `trading/strategy.py`
- `trading/simulation.py`
- `VALUE_POOL.md`
- `DATA_FEEDS.md`

Discord handbook:

- `discord_handbook/`
- `requirements-discord.txt`
- `handbook/`
