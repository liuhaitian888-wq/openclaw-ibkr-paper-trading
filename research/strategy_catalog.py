import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class StrategyCatalogEntry:
    name: str
    module: str
    class_name: str
    family: str
    status: str
    data_requirements: list[str] = field(default_factory=list)
    risk_controls: list[str] = field(default_factory=list)
    book_sources: list[str] = field(default_factory=list)
    book_principles: list[str] = field(default_factory=list)
    next_validation_steps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyCatalog:
    source: str
    created_at: str
    status: str
    summary: str
    entries: list[StrategyCatalogEntry] = field(default_factory=list)


def build_strategy_catalog() -> StrategyCatalog:
    entries = [
        StrategyCatalogEntry(
            name="dual_moving_average",
            module="strategies.dual_ma",
            class_name="DualMovingAverageStrategy",
            family="trend_following",
            status="implemented_paper_wiring_ready",
            data_requirements=["ordered price history", "bid/ask or midpoint for limit price"],
            risk_controls=["one-share target quantity", "shared RiskEngine quantity/value gates", "paper-only execution path"],
            book_sources=[
                "Ernest P. Chan, Quantitative Trading",
                "Robert Carver, Systematic Trading",
            ],
            book_principles=[
                "Quantitative Trading: start with simple, inspectable rules before complex models",
                "Systematic Trading: translate a repeatable forecast into bounded position changes",
            ],
            next_validation_steps=[
                "Run delayed IBKR quote capture after preflight is ready",
                "Compare signal stability across delayed and real-time market data",
                "Paper validate-only before any one-share paper order",
            ],
        ),
        StrategyCatalogEntry(
            name="zscore_mean_reversion",
            module="strategies.mean_reversion",
            class_name="ZScoreMeanReversionStrategy",
            family="mean_reversion",
            status="implemented_research_pipeline_ready",
            data_requirements=["rolling price window", "bid/ask or midpoint for limit price"],
            risk_controls=["entry z-score threshold", "exit band", "one-share target quantity", "shared RiskEngine gates"],
            book_sources=[
                "Ernest P. Chan, Algorithmic Trading",
                "Marcos Lopez de Prado, Advances in Financial Machine Learning",
            ],
            book_principles=[
                "Algorithmic Trading: use explicit mean-reversion diagnostics and entry/exit statistics",
                "Advances in Financial Machine Learning: require out-of-sample and paper evidence before trusting a signal",
            ],
            next_validation_steps=[
                "Run mean-reversion diagnostics on IBKR-recorded quotes",
                "Reject candidates with weak oscillation or trend contamination",
                "Promote only validate-approved one-share payloads to manual review",
            ],
        ),
        StrategyCatalogEntry(
            name="grid_rebalance",
            module="strategies.grid",
            class_name="GridStrategy",
            family="inventory_rebalancing",
            status="implemented_simulation_only",
            data_requirements=["reference price", "latest price", "bid/ask or midpoint for limit price"],
            risk_controls=["max position cap", "grid percentage band", "shared RiskEngine gates"],
            book_sources=[
                "Robert Carver, Systematic Trading",
                "Ernest P. Chan, Quantitative Trading",
            ],
            book_principles=[
                "Systematic Trading: position changes should be bounded, systematic, and risk-budget aware",
                "Quantitative Trading: test simple execution-sensitive rules before scaling them",
            ],
            next_validation_steps=[
                "Add transaction-cost and spread sensitivity diagnostics",
                "Require explicit inventory and drawdown limits before paper validation",
            ],
        ),
        StrategyCatalogEntry(
            name="lightgbm_style_baseline",
            module="strategies.ml_baseline",
            class_name="LightGbmStyleBaselineStrategy",
            family="machine_learning_baseline",
            status="placeholder_feature_consumer",
            data_requirements=["precomputed ml_up_probability feature", "bid/ask or midpoint for limit price"],
            risk_controls=["probability threshold band", "one-share target quantity", "shared RiskEngine gates"],
            book_sources=[
                "Marcos Lopez de Prado, Advances in Financial Machine Learning",
                "Ernest P. Chan, Algorithmic Trading",
            ],
            book_principles=[
                "Advances in Financial Machine Learning: separate model research from execution and guard against overfitting",
                "Algorithmic Trading: deploy model outputs only after transparent validation and paper evidence",
            ],
            next_validation_steps=[
                "Define feature pipeline with train/test split and leakage checks",
                "Add purged or walk-forward validation before using live paper signals",
                "Keep as non-production baseline until validation reports exist",
            ],
        ),
    ]
    return StrategyCatalog(
        source="strategy_catalog",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="modular_catalog_ready",
        summary="Implemented strategy modules share a signal interface and are governed by paper-only risk, validation, and evidence gates.",
        entries=entries,
    )


def write_strategy_catalog_json(catalog: StrategyCatalog, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(catalog), indent=2, sort_keys=True), encoding="utf-8")
    return output


def write_strategy_catalog_markdown(catalog: StrategyCatalog, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(catalog), encoding="utf-8")
    return output


def render_markdown(catalog: StrategyCatalog) -> str:
    lines = [
        "# Strategy Catalog",
        "",
        f"Generated: `{catalog.created_at}`",
        "",
        f"Status: `{catalog.status}`",
        "",
        catalog.summary,
        "",
    ]
    for entry in catalog.entries:
        lines.extend(
            [
                f"## {entry.name}",
                "",
                f"- Module: `{entry.module}`",
                f"- Class: `{entry.class_name}`",
                f"- Family: `{entry.family}`",
                f"- Status: `{entry.status}`",
                "",
                "### Data Requirements",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in entry.data_requirements)
        lines.extend(["", "### Risk Controls", ""])
        lines.extend(f"- {item}" for item in entry.risk_controls)
        lines.extend(["", "### Book Sources", ""])
        lines.extend(f"- {item}" for item in entry.book_sources)
        lines.extend(["", "### Book Principles", ""])
        lines.extend(f"- {item}" for item in entry.book_principles)
        lines.extend(["", "### Next Validation Steps", ""])
        lines.extend(f"- {item}" for item in entry.next_validation_steps)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the strategy module catalog and book-principle mapping.")
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "reports" / "strategy_catalog.json")
    parser.add_argument("--output-md", type=Path, default=PROJECT_ROOT / "reports" / "strategy_catalog.md")
    args = parser.parse_args()

    catalog = build_strategy_catalog()
    write_strategy_catalog_json(catalog, args.output_json)
    write_strategy_catalog_markdown(catalog, args.output_md)
    print(json.dumps(asdict(catalog), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
