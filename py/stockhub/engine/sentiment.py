"""Daily sentiment per stock (PLAN.md section 5, D-140): pure functions over linked items.

An item counts for the first trading day whose close (13:30 Taipei) is at or after its
publication, so a day's figure only uses what was known before that day closed; news on a
holiday or after the close counts for the next session. Each item weighs its link weight
times its importance (3 when unknown, e.g. a forum post scored by the author's own tag).
Duplicates of an event are counted once (callers pass representative items only).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time

from stockhub.common.timeutil import TAIPEI

CLOSE = time(13, 30)
BULLISH = 0.3
BEARISH = -0.3
DEFAULT_IMPORTANCE = 3
AUTHOR_SENTIMENT = 0.8
"""Sentiment of a post the author tagged 看多 (+) or 看空 (-)."""


def trade_date_for(published_at: datetime, trading_days: Sequence[date]) -> date | None:
    """First trading day (sorted list) whose 13:30 Taipei close is at or after the time;
    None when the list ends before that."""
    local = published_at.astimezone(TAIPEI)
    day = local.date() if local.time() <= CLOSE else None
    if day is None:
        index = bisect.bisect_right(trading_days, local.date())
    else:
        index = bisect.bisect_left(trading_days, day)
    return trading_days[index] if index < len(trading_days) else None


@dataclass(frozen=True)
class LinkedItem:
    """One representative item as linked to one stock."""

    stock_id: int
    published_at: datetime
    scope: str
    """news, announcement or the social source code."""
    weight: float
    sentiment: float | None
    """The link's own tone, else the item's; None = not scored."""
    importance: int | None = None
    pushes: int = 0
    boos: int = 0


@dataclass
class DailySentiment:
    stock_id: int
    trade_date: date
    scope: str
    items: int = 0
    scored: int = 0
    bullish: int = 0
    bearish: int = 0
    pushes: int = 0
    boos: int = 0
    _weighted: float = field(default=0.0, repr=False)
    _weights: float = field(default=0.0, repr=False)

    @property
    def sentiment(self) -> float | None:
        if not self._weights:
            return None
        return round(self._weighted / self._weights, 3)

    def add(self, item: LinkedItem) -> None:
        self.items += 1
        self.pushes += item.pushes
        self.boos += item.boos
        if item.sentiment is None:
            return
        self.scored += 1
        weight = item.weight * (item.importance or DEFAULT_IMPORTANCE)
        self._weighted += weight * item.sentiment
        self._weights += weight
        if item.sentiment >= BULLISH:
            self.bullish += 1
        elif item.sentiment <= BEARISH:
            self.bearish += 1


def aggregate(
    items: Iterable[LinkedItem], trading_days: Sequence[date]
) -> dict[tuple[int, date, str], DailySentiment]:
    """(stock_id, trade_date, scope) -> figures, with an 'all' scope over every item."""
    out: dict[tuple[int, date, str], DailySentiment] = {}
    for item in items:
        day = trade_date_for(item.published_at, trading_days)
        if day is None:
            continue
        for scope in (item.scope, "all"):
            key = (item.stock_id, day, scope)
            if key not in out:
                out[key] = DailySentiment(item.stock_id, day, scope)
            out[key].add(item)
    return out


def author_sentiment(stance: str | None) -> float | None:
    return {"bullish": AUTHOR_SENTIMENT, "bearish": -AUTHOR_SENTIMENT}.get(stance or "")


BUZZ_HISTORY_DAYS = 20
BUZZ_MIN_HISTORY = 10
"""Days of forum history needed before a spike can be judged (none right after launch)."""


def buzz_threshold(history: Sequence[int], sigma: float, minimum: int) -> float:
    """Posts per day that count as a spike: mean + sigma * standard deviation of the recent
    days (calendar days, zeros included), at least `minimum`."""
    if len(history) < BUZZ_MIN_HISTORY:
        return float("inf")
    mean = sum(history) / len(history)
    variance = sum((n - mean) ** 2 for n in history) / len(history)
    return max(float(minimum), mean + sigma * math.sqrt(variance))
