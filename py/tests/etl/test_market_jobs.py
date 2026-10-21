"""Market and macro jobs end to end against recorded responses (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.etl.jobs import markets
from stockhub.etl.jobs.base import JobRunResult, run_job
from stockhub.etl.jobs.markets import month_chunks

from .official_sources import official_handler, official_router

TODAY = date(2026, 10, 21)


def _runner(engine: Engine, tmp_path: Path, handler: Any = official_handler) -> Any:
    store = LocalRawStore(engine, tmp_path)
    router = official_router(store, handler)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name, params, engine=engine, rawstore=store, notifier=ConsoleNotifier(), router=router
        )

    return _run


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(markets, "taipei_today", lambda: TODAY)
    return _runner(clean_db, tmp_path)


def _rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def _counts(engine: Engine) -> dict[str, int]:
    return dict(
        _rows(
            engine,
            "SELECT series_code, count(*) FROM market_series_values GROUP BY series_code",
        )
    )


def test_month_chunks() -> None:
    assert month_chunks(date(2026, 9, 21), date(2026, 10, 21)) == [
        (date(2026, 9, 21), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 10, 21)),
    ]
    assert month_chunks(date(2025, 12, 5), date(2026, 1, 2))[0][1] == date(2025, 12, 31)
    assert month_chunks(date(2026, 1, 2), date(2026, 1, 1)) == []


def test_sync_markets_catches_up_and_is_idempotent(run: Any, clean_db: Engine) -> None:
    result = run("sync_markets", series="TAIEX,TPEX,SPX,UST10Y")
    assert result.status == "succeeded", result.error
    # Nothing stored yet: the last 30 days (TAIEX/TPEX by month, September is empty).
    assert _counts(clean_db) == {"TAIEX": 13, "TPEX": 13, "SPX": 15, "UST10Y": 12}
    spx = _rows(
        clean_db,
        "SELECT obs_date, open, value, source FROM market_series_values "
        "WHERE series_code = 'SPX' ORDER BY obs_date DESC LIMIT 1",
    )[0]
    assert (spx.obs_date, str(spx.value), spx.source) == (
        date(2026, 10, 20),
        "7712.569800",
        "yahoo",
    )
    assert "TAIEX 13/13 [twse]" in (result.message or "")

    again = run("sync_markets", series="TAIEX,TPEX,SPX,UST10Y")
    assert again.status == "succeeded"
    assert again.rows_written == 0


def test_a_failed_series_fails_the_job_but_keeps_the_others(run: Any, clean_db: Engine) -> None:
    result = run("sync_markets", series="SPX,SOX")
    assert result.status == "failed"
    assert "SOX" in (result.error or "")
    assert _counts(clean_db) == {"SPX": 15}


def test_unknown_series_is_rejected(run: Any) -> None:
    result = run("sync_markets", series="NOPE")
    assert result.status == "failed"
    assert "未知或停用的序列" in (result.error or "")


def test_bad_values_are_quarantined_then_superseded(
    clean_db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(markets, "taipei_today", lambda: TODAY)

    def broken(request: httpx.Request) -> httpx.Response:
        response = official_handler(request)
        if request.url.path.endswith("/MI_5MINS_HIST"):
            return httpx.Response(200, content=response.content.replace(b"49,712.04", b"99,712.04"))
        return response

    result = _runner(clean_db, tmp_path / "a", broken)("sync_markets", series="TAIEX")
    assert result.status == "succeeded", result.error
    pending = _rows(
        clean_db,
        "SELECT obs_date, reasons FROM market_series_quarantine WHERE resolved_at IS NULL",
    )
    assert pending == [(date(2026, 10, 5), ["ohlc_inconsistent", "move_too_large"])]
    assert _counts(clean_db) == {"TAIEX": 12}

    _runner(clean_db, tmp_path / "b")("sync_markets", series="TAIEX")
    assert _counts(clean_db) == {"TAIEX": 13}
    resolved = _rows(clean_db, "SELECT resolution FROM market_series_quarantine")
    assert resolved == [("superseded",)]


def test_backfill_markets_goes_month_by_month_and_checkpoints(run: Any, clean_db: Engine) -> None:
    result = run("backfill_markets", series="TAIEX,UST10Y", start="2026-09-01", end="2026-10-31")
    assert result.status == "succeeded", result.error
    assert "請求 3 次" in (result.message or "")  # TAIEX September + October, UST10Y once
    assert _counts(clean_db) == {"TAIEX": 13, "UST10Y": 12}


def test_sync_macro_stores_the_ndc_release_and_notes_new_months(run: Any, clean_db: Engine) -> None:
    first = run("sync_macro")
    assert first.status == "succeeded", first.error
    signal = _rows(
        clean_db,
        "SELECT obs_date, value, label FROM market_series_values WHERE series_code = 'TW_SIGNAL' "
        "ORDER BY obs_date DESC LIMIT 1",
    )[0]
    assert (signal.obs_date, int(signal.value), signal.label) == (date(2026, 8, 1), 41, "紅燈")
    counts = _counts(clean_db)
    assert counts["TW_LEADING"] > counts["TW_SIGNAL"]  # indices start in 1982, the light in 1984
    events = "SELECT event_date, title FROM macro_events WHERE source = 'auto'"
    assert _rows(clean_db, events) == []  # the first load is history, not a release

    with clean_db.begin() as conn:
        conn.execute(text("DELETE FROM market_series_values WHERE obs_date = '2026-08-01'"))
    second = run("sync_macro")
    assert "景氣燈號有新月份" in (second.message or "")
    assert _rows(clean_db, events) == [(TODAY, "景氣燈號 2026 年 8 月：紅燈 41 分")]


def _seed(
    engine: Engine, code: str, rows: list[tuple[str, str, str | None]], age: timedelta
) -> None:
    with engine.begin() as conn:
        for day, value, label in rows:
            conn.execute(
                text(
                    "INSERT INTO market_series_values (series_code, obs_date, value, label, "
                    "source, fetched_at) VALUES (:c, :d, :v, :l, 'test', :at)"
                ),
                {"c": code, "d": day, "v": value, "l": label, "at": datetime.now(UTC) - age},
            )


def test_macro_alerts_fire_once_per_change(run: Any, clean_db: Engine) -> None:
    _seed(
        clean_db,
        "TW_SIGNAL",
        [("2026-07-01", "37", "黃紅燈"), ("2026-08-01", "41", "紅燈")],
        timedelta(hours=1),
    )
    _seed(
        clean_db,
        "FED_UPPER",
        [("2026-09-16", "4.25", None), ("2026-09-17", "4.00", None)],
        timedelta(hours=1),
    )
    result = run("check_macro_alerts")
    assert result.rows_written == 2
    alerts = _rows(clean_db, "SELECT kind, stock_id, trade_date, title FROM alerts ORDER BY kind")
    assert alerts == [
        (
            "business_signal",
            None,
            date(2026, 8, 1),
            "景氣燈號轉熱：黃紅燈 → 紅燈（2026 年 8 月，41 分）",
        ),
        ("policy_rate", None, date(2026, 9, 17), "Fed 利率調降：目標上限 4.25% → 4%"),
    ]
    assert run("check_macro_alerts").rows_written == 0


def test_macro_alerts_ignore_old_history(run: Any, clean_db: Engine) -> None:
    _seed(
        clean_db,
        "TW_SIGNAL",
        [("2026-07-01", "37", "黃紅燈"), ("2026-08-01", "41", "紅燈")],
        timedelta(days=10),
    )
    assert run("check_macro_alerts").rows_written == 0
