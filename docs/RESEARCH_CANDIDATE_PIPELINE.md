# Research Candidate Pipeline

This pipeline lets OpenClaw/Gemini do broad research while Python remains the
hard gate before anything reaches the strategy universe.

## Flow

```text
LLM/agent idea
-> OpenClaw/Gemini research and evidence collection
-> candidate draft JSON
-> Python hard audit
-> candidate report under reports/candidates/
-> rules or human approval into data/us_equity_universe.csv
-> strategy modules can trade only approved universe symbols
```

## Safety Boundary

- OpenClaw/Gemini may propose candidates, summarize filings/news, and explain
  bull/bear cases.
- OpenClaw/Gemini must not directly edit `data/us_equity_universe.csv`.
- OpenClaw/Gemini must not directly submit orders.
- Python hard audit checks the structured draft, IBKR quote/contract state, and
  deterministic rules before approval.

## Candidate Draft Shape

```json
{
  "symbol": "EXAMPLE",
  "name": "Example Corp",
  "exchange": "NASDAQ",
  "sector": "Technology",
  "tags": ["software", "llm-candidate"],
  "profile": {
    "symbol": "EXAMPLE",
    "pe_ratio": 20.0,
    "forward_pe": 18.0,
    "peg_ratio": 1.2,
    "debt_to_equity": 0.4,
    "revenue_growth_yoy": 0.12,
    "gross_margin": 0.65,
    "operating_margin": 0.22,
    "return_on_invested_capital": 0.18,
    "free_cash_flow_positive": true,
    "earnings_positive": true,
    "analyst_revision_positive": true,
    "average_volume": 5000000
  },
  "pre_review": {
    "model": "gemini-or-gpt",
    "proposed_action": "ADD",
    "confidence": 0.72,
    "thesis": "Short plain-English investment thesis.",
    "bull_case": ["Durable demand", "Improving margins"],
    "bear_case": ["Valuation risk"],
    "catalysts": ["Upcoming earnings"],
    "risks": ["Customer concentration"]
  },
  "evidence": [
    {
      "source": "sec",
      "title": "Latest 10-Q",
      "url": "https://www.sec.gov/...",
      "published_at": "2026-05-01",
      "summary": "Revenue and margin context."
    },
    {
      "source": "news",
      "title": "Recent company news",
      "url": "https://example.com/news",
      "published_at": "2026-06-01",
      "summary": "Catalyst context."
    }
  ]
}
```

## Commands

Build a hard-audit report:

```bash
.venv313/bin/python scripts/review_candidate_report.py candidate.json
```

Approve a hard-audited report into the universe:

```bash
.venv313/bin/python scripts/approve_candidate_to_universe.py reports/candidates/candidate_example_YYYYMMDDTHHMMSSZ.json
```

Use `--dry-run` on the approval command to inspect the row count and target file
without writing.
