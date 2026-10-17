from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection, text

from stockhub.common.trading_calendar import (
    CalendarGapError,
    is_trading_day,
    previous_trading_day,
    trading_days_between,
)


@pytest.fixture
def cal(sa_conn: Connection) -> Connection:
    """Seeded calendar plus a holiday on Fri 2026-10-09 (National Day, observed)."""
    sa_conn.execute(
        text(
            "UPDATE trading_calendar SET is_trading_day = false, note = '國慶日' "
            "WHERE date = '2026-10-09'"
        )
    )
    return sa_conn


def test_is_trading_day(cal: Connection) -> None:
    assert is_trading_day(cal, date(2026, 10, 8))
    assert not is_trading_day(cal, date(2026, 10, 9))  # holiday
    assert not is_trading_day(cal, date(2026, 10, 10))  # Saturday


def test_previous_trading_day_skips_weekend_and_holiday(cal: Connection) -> None:
    assert previous_trading_day(cal, date(2026, 10, 12)) == date(2026, 10, 8)
    assert previous_trading_day(cal, date(2026, 10, 14)) == date(2026, 10, 13)


def test_trading_days_between_is_inclusive(cal: Connection) -> None:
    assert trading_days_between(cal, date(2026, 10, 8), date(2026, 10, 13)) == [
        date(2026, 10, 8),
        date(2026, 10, 12),
        date(2026, 10, 13),
    ]
    assert trading_days_between(cal, date(2026, 10, 10), date(2026, 10, 11)) == []
    assert trading_days_between(cal, date(2026, 10, 13), date(2026, 10, 8)) == []


def test_missing_dates_raise_instead_of_guessing(cal: Connection) -> None:
    cal.execute(text("DELETE FROM trading_calendar WHERE date = '2026-10-07'"))
    with pytest.raises(CalendarGapError):
        is_trading_day(cal, date(2026, 10, 7))
    with pytest.raises(CalendarGapError, match="missing 1 day"):
        trading_days_between(cal, date(2026, 10, 5), date(2026, 10, 9))
    with pytest.raises(CalendarGapError):
        previous_trading_day(cal, date(2026, 10, 8))
    with pytest.raises(CalendarGapError):
        is_trading_day(cal, date(2040, 1, 2))  # beyond the seeded range
