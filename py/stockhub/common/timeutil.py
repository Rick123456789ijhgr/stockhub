"""Time helpers. Storage is UTC (timestamptz) or Taipei trading dates (date); never naive."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def utcnow() -> datetime:
    return datetime.now(UTC)


def taipei_today(now: datetime | None = None) -> date:
    """Current calendar date in Taipei (the trading-date reference)."""
    return (now or utcnow()).astimezone(TAIPEI).date()
