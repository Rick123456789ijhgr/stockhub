"""Data quality checks. Rows that fail go to quarantine tables, never to the main tables."""

from __future__ import annotations

from stockhub.etl.providers.base import DailyBar


def check_daily_bar(bar: DailyBar) -> list[str]:
    """Names of failed checks; empty means the bar may be stored."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    present = [p for p in prices if p is not None]
    if not present:
        # No regular-session trade. Volume can still be non-zero from after-hours or block
        # trades (seen on TWSE, e.g. 2321 on 2026-10-16), so this is normal, not an anomaly.
        return []
    reasons: list[str] = []
    if len(present) != len(prices):
        reasons.append("partial_ohlc")
    if any(p <= 0 for p in present):
        reasons.append("non_positive_price")
    if bar.high is not None and bar.low is not None:
        if bar.high < bar.low:
            reasons.append("high_below_low")
        else:
            for label, value in (("open", bar.open), ("close", bar.close)):
                if value is not None and not bar.low <= value <= bar.high:
                    reasons.append(f"{label}_outside_range")
    if bar.volume == 0 and len(present) == len(prices):
        reasons.append("prices_without_volume")
    return reasons
