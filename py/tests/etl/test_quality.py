from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from stockhub.etl.providers.base import DailyBar
from stockhub.etl.quality import check_daily_bar


def bar(
    o: str | None, h: str | None, low: str | None, c: str | None, volume: int = 1000
) -> DailyBar:
    def d(x: str | None) -> Decimal | None:
        return Decimal(x) if x is not None else None

    return DailyBar(
        symbol="2330",
        trade_date=date(2026, 10, 16),
        open=d(o),
        high=d(h),
        low=d(low),
        close=d(c),
        volume=volume,
        turnover=Decimal(0),
    )


@pytest.mark.parametrize(
    ("candidate", "reasons"),
    [
        (bar("10", "11", "9", "10.5"), []),
        (bar(None, None, None, None, volume=0), []),
        (bar(None, None, None, None, volume=10), []),
        (bar("10", None, "9", "10"), ["partial_ohlc"]),
        (bar("10", "9", "11", "10"), ["high_below_low"]),
        (bar("12", "11", "9", "10"), ["open_outside_range"]),
        (bar("10", "11", "9", "8"), ["close_outside_range"]),
        (bar("0", "11", "0", "10"), ["non_positive_price"]),
        (bar("10", "11", "9", "10", volume=0), ["prices_without_volume"]),
    ],
)
def test_check_daily_bar(candidate: DailyBar, reasons: list[str]) -> None:
    assert check_daily_bar(candidate) == reasons
