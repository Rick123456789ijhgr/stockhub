"""Backward price adjustment (還原權值) from corporate action factors.

Each event on ex_date d has a factor f = reference price / close before the event. A bar on
date t is adjusted by the product of the factors of every event after it (ex_date > t), so
the latest prices are unchanged and older prices are scaled onto today's share basis:

    adjusted_price(t) = raw_price(t) * adj_factor(t)

The factor is constant between consecutive ex-dates, so it is stored per date range.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

FACTOR_PLACES = Decimal("1E-10")
"""prices_daily.adj_factor is numeric(18, 10)."""
ONE = Decimal(1)


@dataclass(frozen=True)
class FactorSegment:
    start: date | None
    """First date covered (inclusive); None = from the earliest bar."""
    end: date | None
    """First date not covered (exclusive, an ex_date); None = up to the latest bar."""
    factor: Decimal

    def covers(self, day: date) -> bool:
        return (self.start is None or day >= self.start) and (self.end is None or day < self.end)


def factor_segments(events: Iterable[tuple[date, Decimal]]) -> list[FactorSegment]:
    """Cumulative adj_factor per date range, oldest first; events on one day multiply."""
    per_day: dict[date, Decimal] = {}
    for ex_date, factor in events:
        if factor <= 0:
            raise ValueError(f"factor must be positive, got {factor} on {ex_date}")
        per_day[ex_date] = per_day.get(ex_date, ONE) * factor
    segments: list[FactorSegment] = []
    cumulative, end = ONE, None
    for ex_date in sorted(per_day, reverse=True):
        segments.append(FactorSegment(ex_date, end, _round(cumulative)))
        cumulative *= per_day[ex_date]
        end = ex_date
    segments.append(FactorSegment(None, end, _round(cumulative)))
    return segments[::-1]


def adj_factor_on(segments: Iterable[FactorSegment], day: date) -> Decimal:
    return next(s.factor for s in segments if s.covers(day))


def _round(value: Decimal) -> Decimal:
    return value.quantize(FACTOR_PLACES, rounding=ROUND_HALF_EVEN)
