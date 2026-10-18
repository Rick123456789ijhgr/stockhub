"""Taipei trading-day queries backed by the trading_calendar table.

Dates missing from the table raise CalendarGapError instead of being guessed: a silent
weekday fallback would hide a failed holiday import.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Connection, text


class CalendarGapError(LookupError):
    """The trading calendar has no row for a requested date."""


def is_trading_day(conn: Connection, day: date) -> bool:
    value = conn.execute(
        text("SELECT is_trading_day FROM trading_calendar WHERE date = :d"), {"d": day}
    ).scalar_one_or_none()
    if value is None:
        raise CalendarGapError(f"trading_calendar has no entry for {day.isoformat()}")
    return bool(value)


def previous_trading_day(conn: Connection, day: date) -> date:
    """Latest trading day strictly before `day`."""
    found: date | None = conn.execute(
        text("SELECT max(date) FROM trading_calendar WHERE date < :d AND is_trading_day"),
        {"d": day},
    ).scalar_one()
    if found is None:
        raise CalendarGapError(f"no trading day before {day.isoformat()} in trading_calendar")
    # A gap between the found day and `day` could hide a later trading day.
    _require_coverage(conn, found, day - timedelta(days=1))
    return found


def trading_days_between(conn: Connection, start: date, end: date) -> list[date]:
    """Trading days in [start, end], both inclusive; empty when start > end."""
    if start > end:
        return []
    _require_coverage(conn, start, end)
    rows = conn.execute(
        text(
            "SELECT date FROM trading_calendar WHERE date BETWEEN :a AND :b "
            "AND is_trading_day ORDER BY date"
        ),
        {"a": start, "b": end},
    ).scalars()
    return list(rows)


def _require_coverage(conn: Connection, start: date, end: date) -> None:
    expected = (end - start).days + 1
    found = conn.execute(
        text("SELECT count(*) FROM trading_calendar WHERE date BETWEEN :a AND :b"),
        {"a": start, "b": end},
    ).scalar_one()
    if found != expected:
        raise CalendarGapError(
            f"trading_calendar is missing {expected - found} day(s) between "
            f"{start.isoformat()} and {end.isoformat()}"
        )
