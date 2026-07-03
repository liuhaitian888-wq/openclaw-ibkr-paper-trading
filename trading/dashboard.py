import html
import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional


def render_dashboard_html(
    data: Dict[str, object],
    auto_refresh_seconds: Optional[float] = None,
) -> str:
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    generated_at = datetime.now(timezone.utc).isoformat()
    generated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    refresh_meta = ""
    refresh_text = "Manual refresh"
    if auto_refresh_seconds and auto_refresh_seconds > 0:
        refresh_meta = f'\n  <meta http-equiv="refresh" content="{html.escape(str(auto_refresh_seconds))}">'
        refresh_text = f"Auto refresh every {auto_refresh_seconds:g}s"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>OpenClaw Strategy Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #637083;
      --line: #d9dee7;
      --good: #146c43;
      --bad: #b42318;
      --warn: #9a6700;
      --blue: #1f5fbf;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--line);
      background: #fff;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }}
    h1 {{ margin: 0 0 4px; font-size: 24px; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 18px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 14px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }}
    .span-4 {{ grid-column: span 4; }}
    .span-6 {{ grid-column: span 6; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .metric {{
      display: grid;
      gap: 5px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }}
    .metric strong {{ font-size: 22px; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .header-status {{
      text-align: right;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{
      padding: 8px 7px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      font-size: 12px;
      white-space: nowrap;
    }}
    .ok {{ color: var(--good); }}
    .bad {{ color: var(--bad); }}
    .warn {{ color: var(--warn); }}
    .status-list {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .status-list li {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding: 7px 0;
    }}
    .status-list li:last-child {{ border-bottom: 0; }}
    .bar {{
      height: 8px;
      background: #e7ebf3;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 4px;
    }}
    .bar > span {{
      display: block;
      height: 100%;
      background: var(--blue);
      width: 0%;
    }}
    .event-list {{
      display: grid;
      gap: 8px;
      max-height: 520px;
      overflow: auto;
    }}
    .event {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px;
      background: #fbfcfe;
    }}
    .chart {{
      width: 100%;
      min-height: 220px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      overflow: hidden;
    }}
    .chart svg {{ display: block; width: 100%; height: 220px; }}
    .chart-grid {{ stroke: #d9dee7; stroke-width: 1; }}
    .chart-line {{ fill: none; stroke: var(--blue); stroke-width: 3; }}
    .chart-zero {{ stroke: #9aa5b1; stroke-width: 1.5; stroke-dasharray: 5 5; }}
    .chart-label {{ fill: var(--muted); font-size: 12px; }}
    code {{
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      .span-4, .span-6, .span-8 {{ grid-column: span 12; }}
      main {{ padding: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>OpenClaw Strategy Dashboard</h1>
      <div class="muted">Generated <span id="generated-local"></span> local / {html.escape(generated_at)} UTC. Paper-only simulation view.</div>
    </div>
    <div class="header-status">{html.escape(refresh_text)}</div>
  </header>
  <main id="app"></main>
  <script id="dashboard-data" type="application/json">{embedded}</script>
  <script>
    const data = JSON.parse(document.getElementById('dashboard-data').textContent);
    const generatedAtMs = {generated_at_ms};
    const events = data.events || [];
    const feedErrors = data.feed_errors || [];
    const systemStatus = data.system_status || {{}};
    const tokens = systemStatus.tokens || {{}};
    const requestedSymbols = data.symbols || [];
    const returnedSymbols = data.returned_symbols || [];
    const missingSymbols = data.missing_symbols || [];
    const valuePool = data.value_pool || [];
    const proposals = events.filter(event => event.proposal);
    const submissions = data.submissions || [];
    const enterSignals = events.filter(event => event.signal === 'ENTER_LONG');
    const approved = valuePool.filter(item => item.approved);
    const rejected = valuePool.filter(item => !item.approved);
    const pnlCurve = data.pnl_curve || [];

    function fmt(value, digits = 2) {{
      if (value === null || value === undefined) return 'n/a';
      if (typeof value === 'number') return value.toFixed(digits);
      return String(value);
    }}
    function esc(value) {{
      return String(value ?? '').replace(/[&<>"']/g, ch => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }}[ch]));
    }}
    function compactErrors(errors) {{
      const unique = [...new Set(errors.map(error => String(error)))];
      if (unique.length <= 3) return unique.map(esc).join(' · ');
      return unique.slice(0, 3).map(esc).join(' · ') + ` · +${{unique.length - 3}} more`;
    }}
    function metric(label, value, detail) {{
      return `<div class="metric"><span class="muted">${{esc(label)}}</span><strong>${{esc(value)}}</strong><span class="muted">${{esc(detail || '')}}</span></div>`;
    }}
    function statusClass(ok) {{
      return ok ? 'ok' : 'warn';
    }}
    function statusText(ok) {{
      return ok ? 'set' : 'not set';
    }}
    function systemStatusRows() {{
      const tradingApi = systemStatus.trading_api || {{}};
      const dashboardCache = systemStatus.dashboard_cache || {{}};
      const cacheLabel = dashboardCache.status
        ? `${{dashboardCache.status}}, ${{fmt(dashboardCache.age_seconds, 1)}}s old`
        : 'n/a';
      const rows = [
        ['Dashboard data cache', cacheLabel, Boolean(dashboardCache.single_flight)],
        ['Python -> TWS market data', systemStatus.python_to_tws || 'unknown', systemStatus.market_data_ok],
        [
          'Dashboard quote fallback',
          systemStatus.quote_fallback?.active
            ? `${{systemStatus.quote_fallback.source}} active`
            : 'off',
          systemStatus.quote_fallback?.active
            ? Boolean(systemStatus.quote_fallback.dashboard_quotes_returned)
            : true
        ],
        ['Dashboard -> Trading API', systemStatus.dashboard_to_trading_api || 'unknown', Boolean(tradingApi.reachable)],
        ['Trading lock state', tradingApi.lock_state || 'unknown', tradingApi.lock_state === 'TRADE_LOCK'],
        ['Paper transmit', tradingApi.paper_transmit_enabled === true ? 'enabled' : 'disabled', tradingApi.paper_transmit_enabled === true],
        ['Kill switch', tradingApi.kill_switch_enabled === true ? 'enabled' : 'off', tradingApi.kill_switch_enabled !== true],
        ['TWS order readiness', tradingApi.tws_ready_for_orders === true ? 'ready' : 'not ready', tradingApi.tws_ready_for_orders === true],
        ['Python -> OpenClaw', systemStatus.python_to_openclaw || 'not checked', false],
        ['OpenClaw -> Python', systemStatus.openclaw_to_python || 'not checked', false],
        ['TWS client id', systemStatus.client_id ?? 'n/a', true],
        ['Token OPENCLAW_API_KEY', statusText(tokens.OPENCLAW_API_KEY), Boolean(tokens.OPENCLAW_API_KEY)],
        ['Token TRADE_SESSION_TOKEN', statusText(tokens.TRADE_SESSION_TOKEN), Boolean(tokens.TRADE_SESSION_TOKEN)],
        ['Token DISCORD_BOT_TOKEN', statusText(tokens.DISCORD_BOT_TOKEN), Boolean(tokens.DISCORD_BOT_TOKEN)]
      ];
      return rows.map(row => `<li><span>${{esc(row[0])}}</span><strong class="${{statusClass(row[2])}}">${{esc(row[1])}}</strong></li>`).join('');
    }}
    function scoreBar(score) {{
      const safe = Math.max(0, Math.min(100, Number(score || 0)));
      return `<div>${{fmt(safe, 1)}}<div class="bar"><span style="width:${{safe}}%"></span></div></div>`;
    }}
    function valueRows() {{
      return valuePool.map(item => {{
        const breakdown = item.score_breakdown || {{}};
        return `<tr>
          <td><strong>${{esc(item.symbol)}}</strong></td>
          <td>${{item.approved ? '<span class="pill ok">approved</span>' : '<span class="pill bad">filtered</span>'}}</td>
          <td>${{scoreBar(item.score)}}</td>
          <td>V ${{fmt(breakdown.valuation, 1)}} / Q ${{fmt(breakdown.quality, 1)}} / D ${{fmt(breakdown.demand, 1)}} / S ${{fmt(breakdown.safety, 1)}}</td>
          <td>${{(item.reasons || []).map(esc).join('<br>') || '<span class="muted">none</span>'}}</td>
        </tr>`;
      }}).join('');
    }}
    function cacheRows() {{
      return (data.cache || []).map(item => `<tr>
        <td><strong>${{esc(item.symbol)}}</strong></td>
        <td>${{fmt(item.last, 4)}}</td>
        <td>${{fmt(item.bid, 4)}}</td>
        <td>${{fmt(item.ask, 4)}}</td>
        <td>${{fmt(item.age_ms, 0)}} ms</td>
        <td>${{esc(item.source)}}</td>
      </tr>`).join('');
    }}
    function proposalRows() {{
      if (!proposals.length && !submissions.length) return '<tr><td colspan="7" class="muted">No approved proposals in this run.</td></tr>';
      if (submissions.length) return submissions.map(item => {{
        const p = item.proposal || {{}};
        return `<tr>
          <td>${{esc(p.symbol)}}</td>
          <td>${{esc(p.side)}}</td>
          <td>${{esc(p.quantity)}}</td>
          <td>${{fmt(p.limit_price, 4)}}</td>
          <td>${{fmt(p.stop_price, 4)}}</td>
          <td>${{esc(item.status || item.workflow_step || 'n/a')}}</td>
          <td><code>${{esc(p.idempotency_key)}}</code></td>
        </tr>`;
      }}).join('');
      return proposals.map(event => {{
        const p = event.proposal;
        return `<tr>
          <td>${{esc(p.symbol)}}</td>
          <td>${{esc(p.side)}}</td>
          <td>${{esc(p.quantity)}}</td>
          <td>${{fmt(p.limit_price, 4)}}</td>
          <td>${{fmt(p.stop_price, 4)}}</td>
          <td>${{fmt(p.profit_target_price, 4)}}</td>
          <td><code>${{esc(p.idempotency_key)}}</code></td>
        </tr>`;
      }}).join('');
    }}
    function eventCards() {{
      return events.map(event => `<div class="event">
        <div><strong>${{esc(event.symbol)}}</strong> <span class="pill">${{esc(event.signal)}}</span> <span class="muted">step ${{esc(event.step)}}</span></div>
        <div class="muted">price ${{fmt(event.price, 4)}} · short ${{fmt(event.short_ma, 4)}} · long ${{fmt(event.long_ma, 4)}} · confidence ${{fmt(event.confidence, 2)}}</div>
        <div>${{esc(event.signal_reason)}}</div>
        <div class="${{event.plan_approved ? 'ok' : 'muted'}}">${{event.plan_approved ? 'proposal approved' : 'no proposal'}}: ${{esc(event.plan_reason)}}</div>
      </div>`).join('');
    }}
    function pnlChart() {{
      if (!pnlCurve.length) return '<div class="muted">No P&L samples yet.</div>';
      const width = 920;
      const height = 220;
      const pad = 28;
      const values = pnlCurve.map(point => Number(point.total_pnl || 0));
      const minValue = Math.min(...values, 0);
      const maxValue = Math.max(...values, 0);
      const span = Math.max(0.01, maxValue - minValue);
      const x = index => pad + (pnlCurve.length === 1 ? 0 : index * (width - pad * 2) / (pnlCurve.length - 1));
      const y = value => height - pad - ((value - minValue) / span) * (height - pad * 2);
      const points = values.map((value, index) => `${{x(index).toFixed(1)}},${{y(value).toFixed(1)}}`).join(' ');
      const zeroY = y(0);
      const latest = pnlCurve[pnlCurve.length - 1] || {{}};
      return `<div class="chart">
        <svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="P&L over time">
          <line class="chart-grid" x1="${{pad}}" y1="${{pad}}" x2="${{pad}}" y2="${{height - pad}}"></line>
          <line class="chart-grid" x1="${{pad}}" y1="${{height - pad}}" x2="${{width - pad}}" y2="${{height - pad}}"></line>
          <line class="chart-zero" x1="${{pad}}" y1="${{zeroY.toFixed(1)}}" x2="${{width - pad}}" y2="${{zeroY.toFixed(1)}}"></line>
          <polyline class="chart-line" points="${{points}}"></polyline>
          <text class="chart-label" x="${{pad}}" y="18">max ${{fmt(maxValue, 2)}}</text>
          <text class="chart-label" x="${{pad}}" y="${{height - 8}}">min ${{fmt(minValue, 2)}}</text>
          <text class="chart-label" x="${{width - 180}}" y="18">latest ${{fmt(latest.total_pnl, 2)}}</text>
        </svg>
      </div>`;
    }}
    function pnlRows() {{
      if (!pnlCurve.length) return '<tr><td colspan="5" class="muted">No P&L samples yet.</td></tr>';
      return pnlCurve.slice(-10).map(point => `<tr>
        <td>${{esc(point.step)}}</td>
        <td>${{fmt(point.total_pnl, 4)}}</td>
        <td>${{fmt(point.unrealized_pnl, 4)}}</td>
        <td>${{fmt(point.market_value, 2)}}</td>
        <td>${{esc(point.open_positions ?? 0)}}</td>
      </tr>`).join('');
    }}

    document.getElementById('generated-local').textContent = new Date(generatedAtMs).toLocaleString();
    document.getElementById('app').innerHTML = `
      <div class="grid">
        <section class="span-12">
          <h2>Run Summary</h2>
          <div class="grid">
            <div class="span-4">${{metric('Source', data.source || 'unknown', 'external free sources are delayed or replay-only')}}</div>
            <div class="span-4">${{metric('Returned Symbols', returnedSymbols.length + ' / ' + requestedSymbols.length, missingSymbols.length ? 'missing: ' + missingSymbols.join(', ') : 'all requested symbols returned')}}</div>
            <div class="span-4">${{metric('Signals / Proposals', enterSignals.length + ' / ' + proposals.length, 'paper-only simulation')}}</div>
          </div>
          <p class="muted">Requested: ${{requestedSymbols.map(esc).join(', ') || 'none'}}</p>
          ${{missingSymbols.length ? `<p class="warn">Missing symbols: ${{missingSymbols.map(esc).join(', ')}}</p>` : ''}}
          ${{feedErrors.length ? `<p class="warn">Feed errors: ${{compactErrors(feedErrors)}}</p>` : ''}}
        </section>
        <section class="span-12">
          <h2>System Status</h2>
          <ul class="status-list">${{systemStatusRows()}}</ul>
        </section>
        <section class="span-8">
          <h2>Value Pool</h2>
          <table><thead><tr><th>Symbol</th><th>Status</th><th>Score</th><th>Breakdown</th><th>Reasons</th></tr></thead><tbody>${{valueRows()}}</tbody></table>
        </section>
        <section class="span-4">
          <h2>Quote Cache</h2>
          <table><thead><tr><th>Symbol</th><th>Last</th><th>Bid</th><th>Ask</th><th>Age</th><th>Source</th></tr></thead><tbody>${{cacheRows()}}</tbody></table>
        </section>
        <section class="span-12">
          <h2>Paper Proposals</h2>
          <table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Limit</th><th>Stop</th><th>Target / Status</th><th>Idempotency</th></tr></thead><tbody>${{proposalRows()}}</tbody></table>
        </section>
        <section class="span-12">
          <h2>P&L Timeline</h2>
          ${{pnlChart()}}
          <table><thead><tr><th>Step</th><th>Total P&L</th><th>Unrealized</th><th>Market Value</th><th>Open Positions</th></tr></thead><tbody>${{pnlRows()}}</tbody></table>
        </section>
        <section class="span-12">
          <h2>Signal Timeline</h2>
          <div class="event-list">${{eventCards()}}</div>
        </section>
      </div>
    `;
  </script>
</body>
</html>
"""
