"""Valuation series, percentiles and river-chart bands (twin of web/src/lib/valuation.ts).

Change both sides together and regenerate testdata/valuation.json with
py/scripts/gen_valuation_fixture.py (CLAUDE.md rule 11).

- Prices are raw (unadjusted) closes: EPS and book value are per share of that time.
- Each day uses the latest quarter whose available_date (publish date, else the statutory
  deadline) is on or before it, so no figure is used before it was public.
- P/E needs a positive TTM EPS (loss periods are left out); P/B a positive book value.
- Trailing yield = cash dividends with an ex-date in the 365 days up to the day / close.
- Percentile = (values below + half the values equal) / count, over the window.
- River bands: multiples evenly spaced from the 5th to the 95th percentile of the window
  (linear-interpolated quantiles), price = TTM EPS (or book value) x multiple.
Dates are ISO strings (YYYY-MM-DD) on both sides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Metric = Literal["pe", "pb", "dividend_yield"]
BAND_QUANTILES = (0.05, 0.95)
BAND_COUNT = 5


@dataclass(frozen=True)
class PricePoint:
    date: str
    close: float


@dataclass(frozen=True)
class QuarterPoint:
    period_end: str
    available_date: str
    eps_ttm: float | None
    bvps: float | None


@dataclass(frozen=True)
class Dividend:
    ex_date: str
    cash: float


@dataclass(frozen=True)
class ValuationPoint:
    date: str
    close: float
    eps_ttm: float | None
    bvps: float | None
    pe: float | None
    pb: float | None
    dividend_ttm: float
    dividend_yield: float | None


def shift_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def shift_years(iso: str, years: int) -> str:
    """Same month and day `years` earlier/later; Feb 29 falls back to Feb 28."""
    year, rest = int(iso[:4]) + years, iso[4:]
    if rest == "-02-29":
        rest = "-02-28"
    return f"{year:04d}{rest}"


def valuation_series(
    prices: Sequence[PricePoint],
    quarters: Sequence[QuarterPoint],
    dividends: Sequence[Dividend],
) -> list[ValuationPoint]:
    """One point per price (oldest first)."""
    by_available = sorted(quarters, key=lambda q: (q.available_date, q.period_end))
    divs = sorted(dividends, key=lambda d: d.ex_date)
    out: list[ValuationPoint] = []
    current: QuarterPoint | None = None
    next_q = 0
    for p in sorted(prices, key=lambda x: x.date):
        while next_q < len(by_available) and by_available[next_q].available_date <= p.date:
            candidate = by_available[next_q]
            if current is None or candidate.period_end >= current.period_end:
                current = candidate
            next_q += 1
        start = shift_days(p.date, -365)
        dividend = sum(d.cash for d in divs if start < d.ex_date <= p.date)
        eps = current.eps_ttm if current else None
        bvps = current.bvps if current else None
        out.append(
            ValuationPoint(
                date=p.date,
                close=p.close,
                eps_ttm=eps,
                bvps=bvps,
                pe=p.close / eps if eps is not None and eps > 0 and p.close > 0 else None,
                pb=p.close / bvps if bvps is not None and bvps > 0 and p.close > 0 else None,
                dividend_ttm=dividend,
                dividend_yield=dividend / p.close if p.close > 0 else None,
            )
        )
    return out


def window(points: Sequence[ValuationPoint], years: int) -> list[ValuationPoint]:
    """Points from `years` before the last point's date through the last point."""
    if not points:
        return []
    start = shift_years(points[-1].date, -years)
    return [p for p in points if p.date >= start]


def metric_values(points: Sequence[ValuationPoint], metric: Metric) -> list[float]:
    values = [getattr(p, metric) for p in points]
    return [v for v in values if v is not None]


def percentile_rank(values: Sequence[float], current: float) -> float | None:
    if not values:
        return None
    below = sum(1 for v in values if v < current)
    equal = sum(1 for v in values if v == current)
    return (below + 0.5 * equal) / len(values)


def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


@dataclass(frozen=True)
class MetricSummary:
    current: float | None
    percentile: float | None
    low: float | None
    median: float | None
    high: float | None
    count: int


def summarize(points: Sequence[ValuationPoint], metric: Metric, years: int) -> MetricSummary:
    """Where the latest value sits in the last `years` (None when it is undefined, e.g. a
    loss for P/E)."""
    values = metric_values(window(points, years), metric)
    current = getattr(points[-1], metric) if points else None
    return MetricSummary(
        current=current,
        percentile=percentile_rank(values, current) if current is not None else None,
        low=min(values) if values else None,
        median=quantile(values, 0.5),
        high=max(values) if values else None,
        count=len(values),
    )


def band_multiples(values: Sequence[float], count: int = BAND_COUNT) -> list[float]:
    """`count` multiples evenly spaced between the 5th and 95th percentile."""
    low, high = (quantile(values, q) for q in BAND_QUANTILES)
    if low is None or high is None:
        return []
    if count == 1 or high == low:
        return [low]
    step = (high - low) / (count - 1)
    return [low + step * i for i in range(count)]


def river_bands(
    points: Sequence[ValuationPoint], metric: Literal["pe", "pb"], multiples: Sequence[float]
) -> list[list[float | None]]:
    """Per point, the price at each multiple (None while the base is not positive)."""
    out = []
    for p in points:
        base = p.eps_ttm if metric == "pe" else p.bvps
        out.append([base * m if base is not None and base > 0 else None for m in multiples])
    return out
