"""Alert thresholds (PLAN.md section 5).

A holding's daily move is unusual when it exceeds k times the standard deviation of its
recent daily returns, but never less than `floor` (quiet stocks would alert on noise) and
never more than `cap` (a volatile stock must still alert near the 10% price limit; limit
moves land a little under 10% after rounding to the tick, hence 9.5%).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

K = 2.5
FLOOR = 0.03
CAP = 0.095
WINDOW = 20
MIN_RETURNS = 5


def daily_returns(closes: Sequence[float]) -> list[float]:
    """Close-to-close returns of adjusted closes, oldest first."""
    return [b / a - 1 for a, b in pairwise(closes) if a > 0]


def move_threshold(
    closes: Sequence[float], k: float = K, floor: float = FLOOR, cap: float = CAP
) -> float:
    """Threshold for the next day's |return| from the adjusted closes before it (oldest
    first; the last WINDOW returns count). Sample standard deviation; with fewer than
    MIN_RETURNS returns (new listings) the floor applies."""
    returns = daily_returns(closes)[-WINDOW:]
    if len(returns) < MIN_RETURNS:
        return floor
    mean = sum(returns) / len(returns)
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    return min(cap, max(floor, k * sd))
