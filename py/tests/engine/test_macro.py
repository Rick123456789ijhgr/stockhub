from __future__ import annotations

from datetime import date
from decimal import Decimal

from stockhub.engine.macro import Point, light_change, rate_change


def _p(day: int, value: str, label: str | None = None) -> Point:
    return Point(date(2026, day, 1), Decimal(value), label)


def test_light_change_only_on_a_new_colour() -> None:
    assert light_change([_p(7, "37", "黃紅燈"), _p(8, "38", "黃紅燈")]) is None
    change = light_change([_p(7, "31", "綠燈"), _p(8, "30", "黃藍燈")])
    assert change is not None
    assert change.obs_date == date(2026, 8, 1)
    assert not change.rising
    hotter = light_change([_p(7, "31", "綠燈"), _p(8, "32", "黃紅燈")])
    assert hotter is not None
    assert hotter.rising
    assert light_change([_p(8, "41", "紅燈")]) is None
    assert light_change([_p(7, "41", None), _p(8, "41", "紅燈")]) is None


def test_rate_change() -> None:
    assert rate_change([_p(8, "4.25"), _p(9, "4.25")]) is None
    cut = rate_change([_p(8, "4.25"), _p(9, "4.00")])
    assert cut is not None
    assert not cut.rising
    assert rate_change([]) is None
