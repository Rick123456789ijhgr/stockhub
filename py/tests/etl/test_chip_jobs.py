"""Chip jobs end to end against the recorded TWSE/TPEx/TDCC responses (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs import chips
from stockhub.etl.jobs.base import JobRunResult, run_job

from .official_sources import official_handler, official_router

DAY = date(2026, 10, 16)
STOCKS = [
    ("2330", "twse", "stock"),
    ("2002", "twse", "stock"),
    ("0050", "twse", "etf"),
    ("6488", "tpex", "stock"),
    ("006201", "tpex", "etf"),
]


def _seed_stocks(engine: Engine) -> None:
    with engine.begin() as conn:
        for symbol, market, kind in STOCKS:
            conn.execute(
                text(
                    "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                    "VALUES (:s, :m, :t, :s, '2000-01-03')"
                ),
                {"s": symbol, "m": market, "t": kind},
            )


def _runner(engine: Engine, tmp_path: Path, handler: Any = official_handler) -> Any:
    store = LocalRawStore(engine, tmp_path)
    router = official_router(store, handler)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name, params, engine=engine, rawstore=store, notifier=ConsoleNotifier(), router=router
        )

    return _run


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path) -> Any:
    _seed_stocks(clean_db)
    return _runner(clean_db, tmp_path)


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def test_sync_chips_stores_one_day_of_every_table(run: Any, clean_db: Engine) -> None:
    result = run("sync_chips", date=DAY.isoformat())
    assert result.status == "succeeded", result.error
    trades = dict(
        _rows(
            clean_db,
            "SELECT s.symbol, t.total_net FROM institutional_trades_daily t "
            "JOIN stocks s ON s.id = t.stock_id",
        )
    )
    assert trades == {
        "2330": -22_371_830,
        "2002": 44_262_671,
        "0050": -57_179_159,
        "6488": -4_382_391,
        "006201": -101_383,
    }
    margin = dict(
        _rows(
            clean_db,
            "SELECT s.symbol, m.margin_balance FROM margin_daily m "
            "JOIN stocks s ON s.id = m.stock_id",
        )
    )
    assert margin == {"2330": 34_110_000, "0050": 23_887_000, "6488": 13_969_000}
    holdings = _rows(clean_db, "SELECT count(*) FROM foreign_holdings_daily")
    assert holdings[0][0] == 3  # 2330, 0050, 6488 (8455 is not in the master)
    totals = _rows(
        clean_db,
        "SELECT market, net_amount FROM market_institutional_daily WHERE investor = 'total' "
        "ORDER BY market",
    )
    assert [(m, int(v)) for m, v in totals] == [("tpex", -5_190_759_111), ("twse", -68_513_664_272)]
    assert len(_rows(clean_db, "SELECT 1 FROM market_margin_daily")) == 2
    coverage = _rows(
        clean_db, "SELECT dataset, market, rows FROM chip_coverage ORDER BY dataset, market"
    )
    assert ("institutional", "twse", 3) in coverage
    assert ("margin", "tpex", 2) in coverage
    assert len(coverage) == 8
    assert "三大法人 收到 5、寫入 5" in (result.message or "")

    again = run("sync_chips", date=DAY.isoformat())
    assert again.status == "succeeded"
    assert again.rows_written == 0  # idempotent


def test_bad_rows_are_quarantined_then_superseded(clean_db: Engine, tmp_path: Path) -> None:
    _seed_stocks(clean_db)

    def broken(request: httpx.Request) -> httpx.Response:
        response = official_handler(request)
        if request.url.path.endswith("/T86"):
            body = response.content.replace(b'"-22,371,830"', b'"-22,371,831"')
            return httpx.Response(200, content=body)
        return response

    result = _runner(clean_db, tmp_path / "a", broken)(
        "sync_chips", date=DAY.isoformat(), datasets="institutional"
    )
    assert result.status == "succeeded"
    quarantined = _rows(clean_db, "SELECT dataset, reasons, resolution FROM chip_quarantine")
    assert quarantined == [("institutional", ["total_mismatch"], None)]
    assert len(_rows(clean_db, "SELECT 1 FROM institutional_trades_daily")) == 4

    _runner(clean_db, tmp_path / "b")("sync_chips", date=DAY.isoformat(), datasets="institutional")
    assert _rows(clean_db, "SELECT resolution FROM chip_quarantine") == [("superseded",)]
    assert len(_rows(clean_db, "SELECT 1 FROM institutional_trades_daily")) == 5


def test_catch_up_fills_missing_tables_once(
    run: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Monday 2026-10-19 at 11:00 Taipei: today's tables are not tried yet.
    monkeypatch.setattr(chips, "taipei_today", lambda: date(2026, 10, 19))
    monkeypatch.setattr(chips, "utcnow", lambda: datetime(2026, 10, 19, 3, tzinfo=UTC))
    first = run("sync_chips")
    assert first.status == "succeeded", first.error
    assert first.message is not None
    assert "～2026-10-16：" in first.message
    # Every other day answers like a holiday: past days are recorded as covered, empty.
    rows = dict(
        _rows(
            clean_db,
            "SELECT trade_date, sum(rows) FROM chip_coverage GROUP BY trade_date",
        )
    )
    assert len(rows) == 10
    assert rows[DAY] > 0
    assert rows[date(2026, 10, 15)] == 0
    second = run("sync_chips")
    assert second.status == "skipped"


def test_today_unpublished_is_left_pending(
    run: Any, clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chips, "taipei_today", lambda: date(2026, 10, 19))
    result = run("sync_chips", date="2026-10-19")
    assert result.status == "succeeded"
    assert "尚未公布 8 份" in (result.message or "")
    assert _rows(clean_db, "SELECT 1 FROM chip_coverage") == []


def test_backfill_resumes_and_respects_source_start_dates(run: Any, clean_db: Engine) -> None:
    result = run("backfill_chips", start="2014-11-27", end="2014-12-01")
    assert result.status == "succeeded", result.error
    coverage = {
        (r.dataset, r.market, r.trade_date)
        for r in _rows(clean_db, "SELECT dataset, market, trade_date FROM chip_coverage")
    }
    # TPEx per-stock institutional data starts on 2014-12-01; its summary only in 2019.
    assert ("institutional", "tpex", date(2014, 11, 28)) not in coverage
    assert ("institutional", "tpex", date(2014, 12, 1)) in coverage
    assert ("institutional", "twse", date(2014, 11, 28)) in coverage
    assert not any(d == "market_institutional" and m == "tpex" for d, m, _ in coverage)
    checkpoint = _rows(
        clean_db, "SELECT checkpoint FROM job_runs WHERE job_name = 'backfill_chips'"
    )
    assert checkpoint == [(None,)]  # finished runs keep no resume point

    again = run("backfill_chips", start="2014-11-27", end="2014-12-01")
    assert "請求 0 次" in (again.message or "")


def test_unknown_dataset_fails(run: Any) -> None:
    result = run("sync_chips", date=DAY.isoformat(), datasets="lending")
    assert result.status == "failed"
    assert "未知的資料集" in (result.error or "")


def test_distribution_stored_once_per_week(run: Any, clean_db: Engine) -> None:
    result = run("sync_shareholding_distribution")
    assert result.status == "succeeded", result.error
    assert result.message == "集保 2026-10-16：收到 51、寫入 51"
    whales = dict(
        _rows(
            clean_db,
            "SELECT s.symbol, d.ratio FROM shareholding_distribution d "
            "JOIN stocks s ON s.id = d.stock_id WHERE d.level = 15",
        )
    )
    assert str(whales["2330"]) == "0.845600"
    assert run("sync_shareholding_distribution").status == "skipped"
    assert run("sync_shareholding_distribution", force=True).rows_written == 0


def test_compute_chip_summary(run: Any, clean_db: Engine) -> None:
    run("sync_chips", date=DAY.isoformat())
    run("sync_shareholding_distribution")
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO prices_daily (stock_id, trade_date, close, volume, turnover, source) "
                "SELECT id, :d, 1000, 44743000, 1, 'test' FROM stocks WHERE symbol = '2330'"
            ),
            {"d": DAY},
        )
    result = run("compute_chip_summary")
    assert result.status == "succeeded", result.error
    assert result.message == "籌碼摘要 5 檔（最新 2026-10-16）"
    row = _rows(
        clean_db,
        "SELECT c.* FROM chip_summary c JOIN stocks s ON s.id = c.stock_id WHERE s.symbol = '2330'",
    )[0]
    assert row.trade_date == DAY
    assert (row.foreign_streak, row.trust_streak, row.dealer_streak) == (-1, 1, -1)
    assert row.foreign_net_5d == row.foreign_net_20d == -22_046_142
    assert float(row.total_volume_ratio_5d) == pytest.approx(-22_371_830 / 44_743_000)
    assert float(row.margin_utilization) == pytest.approx(34_110_000 / 6_483_092_000)
    assert float(row.short_margin_ratio) == pytest.approx(9_000 / 34_110_000)
    assert row.margin_change_5d is None  # one margin day so far
    assert float(row.foreign_ratio) == pytest.approx(0.6874)
    assert row.big_holder_week == DAY
    assert float(row.whale_ratio) == pytest.approx(21_928_634_563 / 25_932_370_067)
    assert row.whale_change_1w is None
