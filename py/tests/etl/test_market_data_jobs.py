"""End-to-end market data jobs against recorded TWSE/TPEx responses (no network)."""

from __future__ import annotations

import json
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
from stockhub.etl.jobs.market_data import (
    DelistingStats,
    apply_delisting,
    calendar_rows,
    stock_ids_on,
    store_daily_bars,
)
from stockhub.etl.providers.base import CalendarEntry, DailyBar, Delisting, RawResponse
from stockhub.etl.providers.tpex import TpexProvider

from .official_sources import fixture, official_router


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
        stats = store_daily_bars(conn, [broken], "twse", None)
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


# ----------------------------------------------------------------------------- delistings


def _add_stock(engine: Engine, symbol: str, market: str, listed: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                "VALUES (:s, :m, 'stock', :s, :d)"
            ),
            {"s": symbol, "m": market, "d": listed},
        )


def test_sync_delistings_inserts_closes_and_skips_transfers(run: Any, clean_db: Engine) -> None:
    _add_stock(clean_db, "3454", "twse", "2005-03-01")  # still active here: gets closed
    _add_stock(clean_db, "8908", "twse", "2026-10-16")  # moved TPEx -> TWSE that day
    result = run("sync_delistings", start_year=2026)
    assert result.status == "succeeded"
    assert result.message == (
        "2026～2026：新增下市 9、現役改標下市 1、轉市場略過 1、已存在 0；以首筆日線修正上市日 0"
    )
    rows = {
        r.symbol: r
        for r in _rows(
            clean_db,
            "SELECT symbol, market, listed_date, listed_date_estimated, delisted_date, "
            "delisting_reason FROM stocks",
        )
    }
    assert rows["3454"].delisted_date == date(2026, 3, 27)
    assert rows["3454"].listed_date_estimated is False
    assert rows["8908"].delisted_date is None
    assert (rows["2867"].market, rows["2867"].listed_date, rows["2867"].listed_date_estimated) == (
        "twse",
        date(1962, 2, 9),
        True,
    )
    assert rows["5371"].delisting_reason is not None
    assert run("sync_delistings", start_year=2026).rows_written == 0  # idempotent


def test_reused_symbol_maps_bars_to_the_listing_alive_that_day(sa_conn: Any) -> None:
    sa_conn.execute(
        text(
            "INSERT INTO stocks (symbol, market, type, name, listed_date, delisted_date) VALUES "
            "('1234', 'twse', 'stock', 'old', '2001-01-01', '2010-06-01'), "
            "('1234', 'tpex', 'stock', 'new', '2015-01-05', NULL), "
            "('5678', 'tpex', 'stock', 'moved', '2026-10-16', NULL)"
        )
    )
    old, new, moved = (
        sa_conn.execute(text("SELECT id FROM stocks WHERE name = :n"), {"n": n}).scalar_one()
        for n in ("old", "new", "moved")
    )
    before = stock_ids_on(sa_conn, date(2010, 5, 31))
    assert (before["1234"], before["5678"]) == (old, moved)
    assert stock_ids_on(sa_conn, date(2010, 6, 1))["1234"] == new
    assert stock_ids_on(sa_conn, date(2020, 1, 2))["1234"] == new


def test_estimated_listing_date_becomes_first_trading_day(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    run("sync_delistings", start_year=2026)
    bar = DailyBar(
        symbol="2867",
        trade_date=date(2025, 3, 3),
        open=Decimal(10),
        high=Decimal(11),
        low=Decimal(9),
        close=Decimal(10),
        volume=1000,
        turnover=Decimal(10000),
    )
    with clean_db.begin() as conn:
        assert store_daily_bars(conn, [bar], "twse", None).written == 1
        # After its delisting date the symbol is unknown again.
        late = bar.model_copy(update={"trade_date": date(2026, 9, 1)})
        assert store_daily_bars(conn, [late], "twse", None).unknown == 1
    assert run("sync_delistings", start_year=2026).rows_written == 1
    assert _rows(
        clean_db, "SELECT listed_date, listed_date_estimated FROM stocks WHERE symbol = '2867'"
    ) == [(date(2025, 3, 3), True)]


@pytest.mark.parametrize("order", ["chronological", "reversed"])
def test_cross_market_delistings_merge_into_one_listing(sa_conn: Any, order: str) -> None:
    # 9999 traded on TPEx until 2011-07-22, then on TWSE until 2026-03-27 (like 3454 晶睿).
    items = [
        Delisting(symbol="9999", name="甲", market="tpex", delisted_date=date(2011, 7, 22)),
        Delisting(symbol="9999", name="甲", market="twse", delisted_date=date(2026, 3, 27)),
    ]
    stats = DelistingStats()
    for item in items if order == "chronological" else items[::-1]:
        apply_delisting(sa_conn, item, stats)
    for item in items:  # rerun is a no-op
        apply_delisting(sa_conn, item, stats)
    rows = sa_conn.execute(
        text("SELECT market, listed_date, delisted_date FROM stocks WHERE symbol = '9999'")
    ).all()
    assert rows == [("twse", date(1962, 2, 9), date(2026, 3, 27))]
    assert (stats.inserted, stats.closed) == (1, 0)


def test_same_market_symbol_reuse_keeps_two_listings(sa_conn: Any) -> None:
    stats = DelistingStats()
    for day in (date(2008, 9, 1), date(2020, 5, 4)):
        apply_delisting(
            sa_conn, Delisting(symbol="9998", name="乙", market="twse", delisted_date=day), stats
        )
    rows = sa_conn.execute(
        text(
            "SELECT listed_date, delisted_date FROM stocks WHERE symbol = '9998' "
            "ORDER BY listed_date"
        )
    ).all()
    assert rows == [
        (date(1962, 2, 9), date(2008, 9, 1)),
        (date(2008, 9, 1), date(2020, 5, 4)),
    ]


def test_tpex_zero_prices_without_volume_mean_no_trade() -> None:
    # Until 2011-11 the OTC table printed 0.00 instead of ---- for a day without trades.
    table = json.loads(fixture("tpex_otc_20261016.json"))
    fields = [f.strip() for f in table["tables"][0]["fields"]]  # the source pads names
    row = next(r for r in table["tables"][0]["data"] if r[0] == "6488")
    for name in ("開盤", "最高", "最低", "收盤"):
        row[fields.index(name)] = "0.00"
    row[fields.index("成交股數")] = "0"
    raw = RawResponse(
        "otc_quotes", json.dumps(table, ensure_ascii=False).encode(), {"date": "2026-10-16"}
    )
    [bar] = [b for b in TpexProvider().parse_daily_prices(raw) if b.symbol == "6488"]
    assert (bar.open, bar.close, bar.volume) == (None, None, 0)


def test_reparse_daily_prices_supersedes_quarantine(run: Any, clean_db: Engine) -> None:
    run("sync_stocks")
    run("daily_prices", date="2026-10-16")
    # As if the parser had once quarantined 6488 on that day instead of storing it.
    with clean_db.begin() as conn:
        stock_id = conn.execute(text("SELECT id FROM stocks WHERE symbol = '6488'")).scalar_one()
        conn.execute(text("DELETE FROM prices_daily WHERE stock_id = :id"), {"id": stock_id})
        conn.execute(
            text(
                "INSERT INTO prices_daily_quarantine (stock_id, trade_date, payload, reasons, "
                "source) VALUES (:id, '2026-10-16', '{}', ARRAY['non_positive_price'], 'tpex')"
            ),
            {"id": stock_id},
        )
    result = run("reparse_daily_prices", start="2026-10-16", end="2026-10-16")
    assert result.status == "succeeded", result.message
    assert result.rows_written == 1  # only the missing bar; the rest are unchanged
    assert _rows(clean_db, "SELECT resolution FROM prices_daily_quarantine") == [("superseded",)]
