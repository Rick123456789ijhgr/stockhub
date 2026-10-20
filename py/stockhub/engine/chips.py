"""Chip metrics (籌碼指標): pure functions over daily institutional, margin and holding data.

compute_chip_summary stores the latest values per stock in chip_summary for the site; M7's
feature table reuses these functions for every day, so the screener and the stock page
agree. Inputs are oldest first; None means the source had no row that day.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

SHORT_WINDOW = 5
LONG_WINDOW = 20
BIG_HOLDER_LEVELS = range(12, 16)
"""TDCC brackets of 400 lots and more (400-600, 600-800, 800-1000, over 1000)."""
WHALE_LEVEL = 15
"""TDCC bracket of more than 1000 lots."""
TOTAL_LEVEL = 17


def streak(nets: Sequence[int | None]) -> int:
    """Consecutive days of net buying (positive count) or selling (negative count) up to the
    latest day; 0 when the latest day was flat or missing. A flat or missing day ends a run."""
    latest = nets[-1] if nets else None
    if not latest:
        return 0
    sign = 1 if latest > 0 else -1
    count = 0
    for net in reversed(nets):
        if net is None or net == 0 or (net > 0) != (sign > 0):
            break
        count += 1
    return sign * count


def window_sum(values: Sequence[int | None], days: int) -> int:
    """Sum of the last `days` values; missing days count as 0."""
    return sum(v for v in values[-days:] if v is not None)


def ratio(
    numerator: float | int | Decimal | None, denominator: float | int | Decimal | None
) -> float | None:
    """numerator / denominator, or None when either is missing or the denominator is not
    positive."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def change(values: Sequence[int | float | Decimal | None], days: int) -> float | None:
    """Latest value minus the value `days` entries earlier (None if either is missing)."""
    if len(values) <= days:
        return None
    latest, earlier = values[-1], values[-1 - days]
    if latest is None or earlier is None:
        return None
    return float(latest) - float(earlier)


def holder_ratio(shares_by_level: Mapping[int, int], levels: Sequence[int] | range) -> float | None:
    """Share of TDCC custody held in the given brackets (by shares, against level 17)."""
    total = shares_by_level.get(TOTAL_LEVEL)
    if not total:
        return None
    return sum(shares_by_level.get(level, 0) for level in levels) / total


@dataclass(frozen=True)
class InstitutionalDay:
    foreign_net: int | None
    trust_net: int | None
    dealer_net: int | None
    total_net: int | None
    volume: int | None
    """Shares traded that day (prices_daily.volume)."""


@dataclass(frozen=True)
class InstitutionalSummary:
    foreign_streak: int
    trust_streak: int
    dealer_streak: int
    foreign_net_5d: int
    foreign_net_20d: int
    trust_net_5d: int
    trust_net_20d: int
    dealer_net_5d: int
    dealer_net_20d: int
    total_net_5d: int
    total_net_20d: int
    total_volume_ratio_5d: float | None


def summarize_institutional(days: Sequence[InstitutionalDay]) -> InstitutionalSummary:
    """Streaks and window sums over the trading days with institutional data, oldest first."""
    foreign = [d.foreign_net for d in days]
    trust = [d.trust_net for d in days]
    dealer = [d.dealer_net for d in days]
    total = [d.total_net for d in days]
    volume = window_sum([d.volume for d in days], SHORT_WINDOW)
    return InstitutionalSummary(
        foreign_streak=streak(foreign),
        trust_streak=streak(trust),
        dealer_streak=streak(dealer),
        foreign_net_5d=window_sum(foreign, SHORT_WINDOW),
        foreign_net_20d=window_sum(foreign, LONG_WINDOW),
        trust_net_5d=window_sum(trust, SHORT_WINDOW),
        trust_net_20d=window_sum(trust, LONG_WINDOW),
        dealer_net_5d=window_sum(dealer, SHORT_WINDOW),
        dealer_net_20d=window_sum(dealer, LONG_WINDOW),
        total_net_5d=window_sum(total, SHORT_WINDOW),
        total_net_20d=window_sum(total, LONG_WINDOW),
        total_volume_ratio_5d=ratio(window_sum(total, SHORT_WINDOW), volume),
    )


@dataclass(frozen=True)
class MarginDay:
    margin_balance: int
    margin_limit: int | None
    short_balance: int


@dataclass(frozen=True)
class MarginSummary:
    margin_utilization: float | None
    short_margin_ratio: float | None
    """券資比: short balance / margin balance."""
    margin_change_5d: int | None
    short_change_5d: int | None


def summarize_margin(days: Sequence[MarginDay]) -> MarginSummary | None:
    if not days:
        return None
    latest = days[-1]
    earlier = days[-1 - SHORT_WINDOW] if len(days) > SHORT_WINDOW else None
    return MarginSummary(
        margin_utilization=ratio(latest.margin_balance, latest.margin_limit),
        short_margin_ratio=ratio(latest.short_balance, latest.margin_balance),
        margin_change_5d=latest.margin_balance - earlier.margin_balance if earlier else None,
        short_change_5d=latest.short_balance - earlier.short_balance if earlier else None,
    )


@dataclass(frozen=True)
class HolderSummary:
    big_holder_ratio: float | None
    big_holder_change_1w: float | None
    whale_ratio: float | None
    whale_change_1w: float | None


def summarize_holders(weeks: Sequence[Mapping[int, int]]) -> HolderSummary | None:
    """TDCC weeks (level -> shares), oldest first; changes compare with the week before."""
    if not weeks:
        return None
    big = [holder_ratio(w, BIG_HOLDER_LEVELS) for w in weeks]
    whale = [holder_ratio(w, [WHALE_LEVEL]) for w in weeks]
    return HolderSummary(
        big_holder_ratio=big[-1],
        big_holder_change_1w=change(big, 1),
        whale_ratio=whale[-1],
        whale_change_1w=change(whale, 1),
    )


# ----------------------------------------------------------------------------- alerts

FLOW_SHARE = 0.10
"""An institutional group's net trade of at least 10% of the day's volume is notable
(PLAN.md section 5)."""
FLOW_MIN_TURNOVER = Decimal(50_000_000)
"""Thinly traded days are skipped: below NT$50M turnover a few lots reach 10%."""


@dataclass(frozen=True)
class FlowAlert:
    group: str
    """foreign, trust or dealer."""
    net: int
    share: float
    """net / volume (signed)."""


def institutional_flows(
    nets: Mapping[str, int | None],
    volume: int,
    turnover: Decimal,
    share: float = FLOW_SHARE,
    min_turnover: Decimal = FLOW_MIN_TURNOVER,
) -> list[FlowAlert]:
    """Groups whose net shares reach `share` of the day's volume, each judged on its own."""
    if volume <= 0 or turnover < min_turnover:
        return []
    out = []
    for group in ("foreign", "trust", "dealer"):
        net = nets.get(group)
        if net is None:
            continue
        if abs(net) / volume >= share:
            out.append(FlowAlert(group, net, net / volume))
    return out
