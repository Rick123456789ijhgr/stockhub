"""End-to-end market data jobs against recorded TWSE/TPEx responses (no network)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.market_data import calendar_rows, store_daily_bars
from stockhub.etl.providers.base import CalendarEntry, DailyBar

from .official_sources import official_router


@pytest.fixture
def calendar_reset(engine: Engine) -> Iterator[None]:
    """These jobs rewrite trading_calendar; restore the migration seed afterwards."""
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE trading_calendar SET is_trading_day = extract(isodow FROM date) < 6, "
                "note = 'seed:weekday-rule'"
            )
        )
        conn.execute(text("DELETE FROM trading_calendar WHERE date > '2027-12-31'"))


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path, calendar_reset: None) -> Any:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name,
            params,
            engine=clean_db,
            rawstore=store,
            notifier=ConsoleNotifier(),
            router=router,
        )

    return _run


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


# ----------------------------------------------------------------------------- calendar


def test_calendar_rows_fill_the_whole_year() -> None:
    rows = calendar_rows(
        2026, [CalendarEntry(day=date(2026, 10, 9), name="國慶日", is_trading_day=False)]
    )
    by_day = {r["date"]: r for r in rows}
    assert len(rows) == 365
    assert by_day[date(2026, 10, 9)] == {
        "date": date(2026, 10, 9),
        "is_trading_day": False,
        "note": "國慶日",
    }
    assert by_day[date(2026, 10, 16)]["is_trading_day"] is True
    assert by_day[date(2026, 10, 17)]["is_trading_day"] is False


def test_sync_calendar_imports_published_years_only(run: Any, clean_db: Engine) -> None:
    result = run("sync_calendar", start_year=2026, end_year=2027)
    assert result.status == "succeeded"
    assert result.message == "已匯入：[2026]；尚未公布（保留原本日曆）：[2027]"
    rows = dict(
        (r.date, (r.is_trading_day, r.note))
        for r in _rows(
            clean_db,
            "SELECT date, is_trading_day, note FROM trading_calendar "
            "WHERE date IN ('2026-10-09', '2026-10-16', '2026-02-12', '2027-01-05')",
        )
    )
    assert rows == {
        date(2026, 2, 12): (False, "市場無交易，僅辦理結算交割作業"),
        date(2026, 10, 9): (False, "國慶日"),
        date(2026, 10, 16): (True, "official:2026"),
        date(2027, 1, 5): (True, "seed:weekday-rule"),
    }
    assert run("sync_calendar", start_year=2026).rows_written == 0  # idempotent


# ----------------------------------------------------------------------------- stocks


def test_sync_stocks_loads_both_markets(run: Any, clean_db: Engine) -> None:
    first = run("sync_stocks")
    assert (first.status, first.rows_written) == ("succeeded", 9)
    assert first.message == "主檔：twse 5 檔、tpex 4 檔"
    stocks = {
        r.symbol: (r.market, r.type, r.listed_date)
        for r in _rows(clean_db, "SELECT symbol, market, type, listed_date FROM stocks")
    }
    assert stocks["2330"] == ("twse", "stock", date(1994, 9, 5))
    assert stocks["0050"] == ("twse", "etf", date(2003, 6, 30))
    assert stocks["6488"] == ("tpex", "stock", date(2015, 9, 25))
    assert stocks["006201"] == ("tpex", "etf", date(2011, 1, 27))
    assert run("sync_stocks").rows_written == 0  # idempotent


def test_sync_stocks_updates_renamed_security(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    with clean_db.begin() as conn:
        conn.execute(text("UPDATE stocks SET name = '舊名' WHERE symbol = '2330'"))
    assert run("sync_stocks").rows_written == 1
    assert _rows(clean_db, "SELECT name FROM stocks WHERE symbol = '2330'") == [("台積電",)]


# ----------------------------------------------------------------------------- prices


def test_daily_prices_requires_master(run: Any) -> None:
    result = run("daily_prices", date="2026-10-16")
    assert result.status == "failed"
    assert "請先執行 sync_stocks" in (result.error or "")


def test_daily_prices_stores_both_markets(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    result = run("daily_prices", date="2026-10-16")
    assert (result.status, result.rows_written) == ("succeeded", 4)
    assert result.message == (
        "twse：收到 3、寫入 2、隔離 0、非主檔代號略過 1；"
        "tpex：收到 3、寫入 2、隔離 0、非主檔代號略過 1"
    )
    prices = {
        r.symbol: (r.close, r.adj_factor, r.source)
        for r in _rows(
            clean_db,
            "SELECT s.symbol, p.close, p.adj_factor, p.source FROM prices_daily p "
            "JOIN stocks s ON s.id = p.stock_id",
        )
    }
    assert prices == {
        "0050": (Decimal("109.0000"), Decimal("1.0000000000"), "twse"),
        "2330": (Decimal("2420.0000"), Decimal("1.0000000000"), "twse"),
        "006201": (Decimal("44.5900"), Decimal("1.0000000000"), "tpex"),
        "6488": (Decimal("902.0000"), Decimal("1.0000000000"), "tpex"),
    }
    # Raw responses landed before parsing (rule 5).
    assert {r.provider for r in _rows(clean_db, "SELECT provider FROM raw_objects")} == {
        "twse",
        "tpex",
    }
    # Rerun writes nothing new (rule 4).
    assert run("daily_prices", date="2026-10-16").rows_written == 0


def test_daily_prices_skips_non_trading_days(run: Any) -> None:
    run("sync_stocks")
    result = run("daily_prices", date="2026-10-17")
    assert (result.status, result.error) == ("skipped", "2026-10-17 不是交易日")


def test_bad_bars_go_to_quarantine(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    broken = DailyBar(
        symbol="2330",
        trade_date=date(2026, 10, 16),
        open=Decimal(10),
        high=Decimal(9),
        low=Decimal(11),
        close=Decimal(10),
        volume=100,
        turnover=Decimal(1000),
    )
    with clean_db.begin() as conn:
        stats = store_daily_bars(conn, "twse", [broken], "twse", None)
    assert (stats.written, stats.quarantined) == (0, 1)
    assert _rows(clean_db, "SELECT count(*) FROM prices_daily") == [(0,)]
    assert _rows(clean_db, "SELECT reasons FROM prices_daily_quarantine") == [(["high_below_low"],)]


def test_backfill_derives_closed_days_and_resumes(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    # 10-15 has no TWSE data in the fixtures: with the seed calendar it is marked closed.
    result = run("backfill_prices", start="2026-10-15", end="2026-10-17")
    assert result.status == "succeeded"
    assert result.message == "2026-10-15～2026-10-17：完成 1 個交易日，另有 1 天確認休市"
    assert _rows(
        clean_db, "SELECT is_trading_day, note FROM trading_calendar WHERE date = '2026-10-15'"
    ) == [(False, "derived:no-twse-data")]
    assert _rows(clean_db, "SELECT count(*) FROM prices_daily") == [(4,)]


def test_backfill_stops_when_an_announced_trading_day_has_no_data(run: Any) -> None:
    run("sync_stocks")
    run("sync_calendar", start_year=2026)
    result = run("backfill_prices", start="2026-02-11", end="2026-02-11")  # 春節前最後交易日
    assert result.status == "failed"
    assert "官方公告 2026-02-11" in (result.error or "")


def test_unpublished_future_day_is_an_error_not_a_holiday(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    result = run("backfill_prices", start="2027-01-05", end="2027-01-05")
    assert result.status == "failed"
    assert "尚未公布" in (result.error or "")
    assert _rows(
        clean_db, "SELECT is_trading_day FROM trading_calendar WHERE date = '2027-01-05'"
    ) == [(True,)]
