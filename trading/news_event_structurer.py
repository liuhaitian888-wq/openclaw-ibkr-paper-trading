"""Normalize raw news events into structured news events."""

from trading.auto_open_pipeline import structure_news_event


def normalize(raw_event: dict) -> dict:
    return structure_news_event(raw_event)
