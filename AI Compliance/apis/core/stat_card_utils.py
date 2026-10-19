"""Shared helpers for dashboard stat cards (trends, formatting)."""

from typing import Optional


def format_pct_change_trend(current: int, previous: int) -> Optional[str]:
    """Format period-over-period percent change (e.g. for StatCard subtitles)."""
    if current == 0 and previous == 0:
        return None
    if previous == 0:
        return "+100%" if current > 0 else None
    pct = (current - previous) / previous * 100.0
    sign = "+" if pct >= 0 else ""
    rounded = round(pct, 2)
    if rounded == int(rounded):
        return f"{sign}{int(rounded)}%"
    return f"{sign}{rounded}%"
