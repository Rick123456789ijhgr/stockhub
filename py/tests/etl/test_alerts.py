"""Holding alerts and the replayed holdings they (and the quote poll) use."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.portfolio_store import holdings
from stockhub.etl.jobs.alerts import check_holding_moves, todays_move
from stockhub.etl.jobs.quotes import polled_stocks

TODAY = date(2026, 10, 19)


def _stock(conn: Connection, symbol: str) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                "VALUES (:s, 'twse', 'stock', :s, '2000-01-01') RETURNING id"
            ),
            {"s": symbol},
        ).scalar_one()
    )


def _bars(conn: Connection, stock_id: int, closes: list[float], last: date) -> None:
    """Daily closes ending on `last` (one per calendar day; weekends do not matter here)."""
    for i, close in enumerate(reversed(closes)):
        conn.execute(
            text(
                "INSERT INTO prices_daily (stock_id, trade_date, open, high, low, close, volume, "
                "turnover, source) VALUES (:id, :d, :c, :c, :c, :c, 1000, 1, 'test')"
            ),
            {"id": stock_id, "d": last - timedelta(days=i), "c": close},
        )


def _buy(conn: Connection, stock_id: int, quantity: int, day: str = "2026-09-01") -> None:
    conn.execute(
        text(
            "INSERT INTO portfolio_transactions (stock_id, trade_date, side, quantity, price) "
            "VALUES (:id, :d, 'buy', :q, 100)"
        ),
        {"id": stock_id, "d": day, "q": quantity},
    )


def _quote(conn: Connection, stock_id: int, price: float, prev: float) -> None:
    conn.execute(
        text(
            "INSERT INTO quotes_latest (stock_id, trade_date, quote_time, price, prev_close, "
            "volume, source) VALUES (:id, :d, now(), :p, :prev, 1, 'test')"
        ),
        {"id": stock_id, "d": TODAY, "p": price, "prev": prev},
    )


CALM = [100.0, 100.5] * 11  # about ±0.5% a day: threshold is the 3% floor


def test_holdings_follow_splits_and_sells(sa_conn: Connection) -> None:
    a, b = _stock(sa_conn, "1111"), _stock(sa_conn, "2222")
    _buy(sa_conn, a, 1000)
    _buy(sa_conn, b, 500)
    sa_conn.execute(
        text(
            "INSERT INTO portfolio_transactions (stock_id, trade_date, side, quantity, price) "
            "VALUES (:id, '2026-09-10', 'sell', 500, 100)"
        ),
        {"id": b},
    )
    sa_conn.execute(
        text(
            "INSERT INTO corporate_actions (stock_id, ex_date, action_type, ratio, source) "
            "VALUES (:id, '2026-09-15', 'split', 4, 'test')"
        ),
        {"id": a},
    )
    assert holdings(sa_conn, TODAY) == {a: 4000}
    # Sold out: no longer polled.
    assert [s for s, _, _ in polled_stocks(sa_conn, (), TODAY)] == [a]


def test_intraday_move_beyond_the_threshold_alerts_once(sa_conn: Connection) -> None:
    stock = _stock(sa_conn, "3333")
    _bars(sa_conn, stock, CALM, TODAY - timedelta(days=1))
    _buy(sa_conn, stock, 2000)
    _quote(sa_conn, stock, 104.0, 100.5)  # +3.5%
    out = io.StringIO()
    assert check_holding_moves(sa_conn, ConsoleNotifier(out), TODAY) == 1
    assert "[持股警示] 3333 3333 上漲 3.5%" in out.getvalue()
    row = sa_conn.execute(text("SELECT detail, notified_at FROM alerts")).one()
    assert row.detail["shares"] == 2000
    assert row.detail["source"] == "quote"
    assert row.notified_at is not None
    # The next poll sees the same move: no second alert.
    assert check_holding_moves(sa_conn, ConsoleNotifier(io.StringIO()), TODAY) == 0


def test_small_moves_and_missing_prices_do_not_alert(sa_conn: Connection) -> None:
    stock = _stock(sa_conn, "4444")
    _bars(sa_conn, stock, CALM, TODAY - timedelta(days=1))
    _buy(sa_conn, stock, 1000)
    assert todays_move(sa_conn, stock, TODAY) is None  # no quote, no bar today
    _quote(sa_conn, stock, 102.0, 100.5)  # +1.5%
    move = todays_move(sa_conn, stock, TODAY)
    assert move is not None
    assert move.threshold == 0.03
    assert check_holding_moves(sa_conn, ConsoleNotifier(io.StringIO()), TODAY) == 0


def test_the_close_wins_over_the_last_snapshot(sa_conn: Connection) -> None:
    stock = _stock(sa_conn, "5555")
    _bars(sa_conn, stock, [*CALM, 95.0], TODAY)  # today's close -5.5%
    _buy(sa_conn, stock, 1000)
    _quote(sa_conn, stock, 100.0, 100.5)
    move = todays_move(sa_conn, stock, TODAY)
    assert move is not None
    assert (move.source, move.price) == ("daily", 95.0)
    assert move.change == pytest.approx(95.0 / 100.5 - 1)
    assert check_holding_moves(sa_conn, ConsoleNotifier(io.StringIO()), TODAY) == 1
