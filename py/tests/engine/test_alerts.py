"""Alert thresholds."""

from __future__ import annotations

import pytest

from stockhub.engine.alerts import daily_returns, move_threshold


def test_quiet_and_new_stocks_use_the_floor() -> None:
    assert move_threshold([100.0] * 21) == 0.03
    assert move_threshold([100.0, 101.0, 100.0]) == 0.03  # too short


def test_volatile_stock_scales_with_its_deviation_and_is_capped() -> None:
    swing = [100.0, 102.0] * 11  # returns alternate +2% / -1.96%
    returns = daily_returns(swing)[-20:]
    mean = sum(returns) / 20
    sd = (sum((r - mean) ** 2 for r in returns) / 19) ** 0.5
    assert move_threshold(swing) == pytest.approx(2.5 * sd)
    assert move_threshold([100.0, 106.0] * 11) == 0.095


def test_only_the_last_twenty_returns_count() -> None:
    wild_then_calm = [100.0, 130.0, 100.0] + [100.0] * 21
    assert move_threshold(wild_then_calm) == 0.03
