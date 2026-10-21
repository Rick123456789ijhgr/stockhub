from __future__ import annotations

from decimal import Decimal

import pytest

from stockhub.engine.chips import (
    InstitutionalDay,
    MarginDay,
    change,
    holder_ratio,
    institutional_flows,
    ratio,
    streak,
    summarize_holders,
    summarize_institutional,
    summarize_margin,
    window_sum,
)


@pytest.mark.parametrize(
    ("nets", "expected"),
    [
        ([], 0),
        ([5, 3, 2], 3),
        ([-1, 4, 2], 2),
        ([4, -2, -1, -7], -3),
        ([4, 2, 0], 0),
        ([4, 0, 2], 1),  # a flat day ends the run
        ([4, None, 2], 1),  # so does a missing day
        ([3, None], 0),
    ],
)
def test_streak(nets: list[int | None], expected: int) -> None:
    assert streak(nets) == expected


def test_window_sum_and_change() -> None:
    assert window_sum([1, 2, 3, None, 5], 3) == 8
    assert window_sum([1, 2], 5) == 3
    assert change([10, 12, 15], 2) == 5
    assert change([10, 12], 2) is None
    assert change([None, 12, 15], 2) is None


def test_ratio_guards() -> None:
    assert ratio(1, 4) == 0.25
    assert ratio(1, 0) is None
    assert ratio(None, 4) is None
    assert ratio(Decimal(3), Decimal(6)) == 0.5


def test_summarize_institutional() -> None:
    days = [InstitutionalDay(100, -10, 0, 90, 1000) for _ in range(18)]
    days += [
        InstitutionalDay(-50, 20, 5, -25, 1000),
        InstitutionalDay(-30, 20, None, -10, 1000),
    ]
    s = summarize_institutional(days)
    assert (s.foreign_streak, s.trust_streak, s.dealer_streak) == (-2, 2, 0)
    assert s.foreign_net_5d == 100 * 3 - 80
    assert s.foreign_net_20d == 100 * 18 - 80
    assert s.trust_net_20d == -10 * 18 + 40
    assert s.total_net_5d == 90 * 3 - 35
    assert s.total_volume_ratio_5d == pytest.approx(235 / 5000)


def test_summarize_margin() -> None:
    days = [MarginDay(1000 + i * 10, 10_000, 100 + i) for i in range(7)]
    s = summarize_margin(days)
    assert s is not None
    assert s.margin_utilization == pytest.approx(1060 / 10_000)
    assert s.short_margin_ratio == pytest.approx(106 / 1060)
    assert (s.margin_change_5d, s.short_change_5d) == (50, 5)
    short = summarize_margin(days[:3])
    assert short is not None
    assert short.margin_change_5d is None
    assert summarize_margin([]) is None
    assert summarize_margin([MarginDay(0, None, 0)]) == summarize_margin([MarginDay(0, 0, 0)])


def test_holders() -> None:
    week1 = {1: 100, 12: 50, 15: 300, 17: 1000}
    week2 = {1: 80, 12: 60, 14: 10, 15: 320, 17: 1000}
    assert holder_ratio(week1, range(12, 16)) == pytest.approx(0.35)
    assert holder_ratio({1: 5}, [15]) is None
    s = summarize_holders([week1, week2])
    assert s is not None
    assert s.big_holder_ratio == pytest.approx(0.39)
    assert s.big_holder_change_1w == pytest.approx(0.04)
    assert s.whale_ratio == pytest.approx(0.32)
    assert s.whale_change_1w == pytest.approx(0.02)
    first = summarize_holders([week1])
    assert first is not None
    assert first.whale_change_1w is None


def test_institutional_flows() -> None:
    nets = {"foreign": -150, "trust": 99, "dealer": None}
    alerts = institutional_flows(nets, 1000, Decimal(60_000_000))
    assert [(a.group, a.net, a.share) for a in alerts] == [("foreign", -150, -0.15)]
    # Each group on its own: trust at 9.9% stays quiet even though the sum is larger.
    assert institutional_flows(nets, 1000, Decimal(10_000_000)) == []  # below turnover floor
    assert institutional_flows(nets, 0, Decimal(60_000_000)) == []
