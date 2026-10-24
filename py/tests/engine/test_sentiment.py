"""Daily sentiment aggregation (engine/sentiment.py)."""

from __future__ import annotations

from datetime import date, datetime

from stockhub.common.timeutil import TAIPEI
from stockhub.engine.sentiment import LinkedItem, aggregate, author_sentiment, trade_date_for

# Thu 22, Fri 23, Mon 26 Oct 2026 (Sat-Sun closed).
DAYS = [date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26)]


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TAIPEI)


def test_trade_date_for() -> None:
    assert trade_date_for(_at(22, 8), DAYS) == date(2026, 10, 22)
    assert trade_date_for(_at(22, 13, 30), DAYS) == date(2026, 10, 22)
    assert trade_date_for(_at(22, 13, 31), DAYS) == date(2026, 10, 23)
    # Weekend news counts for Monday.
    assert trade_date_for(_at(24, 10), DAYS) == date(2026, 10, 26)
    assert trade_date_for(_at(23, 20), DAYS) == date(2026, 10, 26)
    # After the known calendar: unknown.
    assert trade_date_for(_at(26, 14), DAYS) is None


def test_aggregate_weights_and_counts() -> None:
    items = [
        LinkedItem(1, _at(22, 9), "news", 1.0, 0.8, importance=5),
        LinkedItem(1, _at(22, 10), "news", 0.3, -0.5, importance=3),
        LinkedItem(1, _at(22, 11), "news", 1.0, None),
        LinkedItem(1, _at(22, 12), "ptt_stock", 1.0, -0.8, pushes=10, boos=2),
        LinkedItem(2, _at(25, 9), "announcement", 1.0, 0.0, importance=1),
    ]
    out = aggregate(items, DAYS)
    news = out[(1, date(2026, 10, 22), "news")]
    assert (news.items, news.scored, news.bullish, news.bearish) == (3, 2, 1, 1)
    # (1*5*0.8 + 0.3*3*-0.5) / (5 + 0.9)
    assert news.sentiment == round((4.0 - 0.45) / 5.9, 3)
    ptt = out[(1, date(2026, 10, 22), "ptt_stock")]
    assert (ptt.pushes, ptt.boos, ptt.sentiment) == (10, 2, -0.8)
    everything = out[(1, date(2026, 10, 22), "all")]
    assert everything.items == 4
    assert everything.pushes == 10
    monday = out[(2, date(2026, 10, 26), "announcement")]
    assert (monday.items, monday.sentiment, monday.bullish, monday.bearish) == (1, 0.0, 0, 0)
    assert (1, date(2026, 10, 23), "news") not in out


def test_unscored_day_and_author_tags() -> None:
    out = aggregate([LinkedItem(3, _at(23, 9), "news", 1.0, None)], DAYS)
    day = out[(3, date(2026, 10, 23), "news")]
    assert (day.items, day.scored, day.sentiment) == (1, 0, None)
    assert author_sentiment("bullish") == 0.8
    assert author_sentiment("bearish") == -0.8
    assert author_sentiment(None) is None


def test_buzz_threshold() -> None:
    from stockhub.engine.sentiment import buzz_threshold

    quiet = [0] * 18 + [1, 1]
    assert buzz_threshold(quiet, 3.0, 5) == 5.0
    busy = [10, 12, 8, 10, 10, 12, 8, 10, 10, 10]
    assert round(buzz_threshold(busy, 3.0, 5), 2) == round(10 + 3 * (1.6**0.5), 2)
    assert buzz_threshold([1] * 9, 3.0, 5) == float("inf")
