"""Macro alert rules (PLAN.md section 5): 景氣燈號變色 and Fed rate decisions.

Pure functions over the stored series; jobs/markets.py feeds them and writes alerts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

LIGHT_ORDER = ("藍燈", "黃藍燈", "綠燈", "黃紅燈", "紅燈")
"""Cold to hot; the index tells whether a change heats up or cools down."""


@dataclass(frozen=True)
class Point:
    obs_date: date
    value: Decimal
    label: str | None = None


@dataclass(frozen=True)
class Change:
    obs_date: date
    """Observation that differs from the one before it."""
    before: Point
    after: Point

    @property
    def rising(self) -> bool:
        if self.after.label in LIGHT_ORDER and self.before.label in LIGHT_ORDER:
            return LIGHT_ORDER.index(self.after.label) > LIGHT_ORDER.index(self.before.label)
        return self.after.value > self.before.value


def light_change(points: Sequence[Point]) -> Change | None:
    """The latest month's light when it differs from the month before (points oldest first)."""
    if len(points) < 2 or points[-1].label is None or points[-2].label is None:
        return None
    before, after = points[-2], points[-1]
    if before.label == after.label:
        return None
    return Change(after.obs_date, before, after)


def rate_change(points: Sequence[Point]) -> Change | None:
    """The latest value of a policy rate when it differs from the previous observation."""
    if len(points) < 2 or points[-1].value == points[-2].value:
        return None
    return Change(points[-1].obs_date, points[-2], points[-1])
