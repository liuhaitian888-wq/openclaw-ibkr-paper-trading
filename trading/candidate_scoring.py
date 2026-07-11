"""Candidate scoring helpers."""

from trading.auto_open_pipeline import score_candidate


def score(symbol: str, details: dict) -> dict:
    return score_candidate(symbol, details)
