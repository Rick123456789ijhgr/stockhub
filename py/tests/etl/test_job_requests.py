"""Website-queued jobs (job_requests) and the repair jobs they run."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from stockhub.common.notifier import ConsoleNotifier
from stockhub.common.rawstore import LocalRawStore
from stockhub.common.timeutil import utcnow
from stockhub.etl.job_requests import LOCK_KEY, drain
from stockhub.etl.jobs.base import JobRunResult, UnknownJobError, run_job
from stockhub.etl.jobs.market_data import stock_missing_days

from .official_sources import official_router


def _queue(engine: Engine, job: str, params: dict[str, Any]) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO job_requests (job_name, params, requested_by) "
                    "VALUES (:j, CAST(:p AS jsonb), 'me@example.com') RETURNING id"
                ),
                {"j": job, "p": json.dumps(params)},
            ).scalar_one()
        )


def _requests(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT id, job_name, status, message, run_id FROM job_requests ORDER BY id")
            ).all()
        )


def test_drain_runs_requests_in_order_and_records_outcomes(clean_db: Engine) -> None:
    first = _queue(clean_db, "daily_prices", {"date": "2026-07-10"})
    second = _queue(clean_db, "catch_up_prices", {})
    with clean_db.begin() as conn:
        run_id = int(
            conn.execute(
                text(
                    'INSERT INTO job_runs (job_name, status, finished_at, "trigger") '
                    "VALUES ('daily_prices', 'skipped', now(), 'manual') RETURNING id"
                )
            ).scalar_one()
        )
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_run(job: str, params: dict[str, Any]) -> JobRunResult:
        calls.append((job, params))
        if job == "catch_up_prices":
            raise UnknownJobError("unknown job")
        return JobRunResult(run_id, job, params, "skipped", 0, message="2026-07-10 證交所無資料")

    assert drain(clean_db, fake_run) == 2
    assert calls == [("daily_prices", {"date": "2026-07-10"}), ("catch_up_prices", {})]
    rows = {r.id: r for r in _requests(clean_db)}
    assert (rows[first].status, rows[first].message) == ("skipped", "2026-07-10 證交所無資料")
    assert rows[first].run_id == run_id
    assert (rows[second].status, rows[second].message) == ("failed", "unknown job")
    assert drain(clean_db, fake_run) == 0  # nothing left


def test_same_pending_request_is_queued_once(clean_db: Engine) -> None:
    _queue(clean_db, "daily_prices", {"date": "2026-07-10"})
    with pytest.raises(Exception, match="job_requests_one_pending_idx"):
        _queue(clean_db, "daily_prices", {"date": "2026-07-10"})


def test_drain_yields_to_a_running_drainer(clean_db: Engine) -> None:
    _queue(clean_db, "catch_up_prices", {})
    with clean_db.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        other.commit()
        try:
            assert drain(clean_db, lambda *_: pytest.fail("must not run")) == 0
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            other.commit()
    assert _requests(clean_db)[0].status == "queued"


def test_stale_running_request_is_abandoned(clean_db: Engine) -> None:
    request_id = _queue(clean_db, "catch_up_prices", {})
    with clean_db.begin() as conn:
        conn.execute(
            text("UPDATE job_requests SET status = 'running', started_at = :t WHERE id = :id"),
            {"t": utcnow() - timedelta(hours=4), "id": request_id},
        )
    drain(clean_db, lambda *_: pytest.fail("nothing queued"))
    assert _requests(clean_db)[0].status == "failed"


# ----------------------------------------------------------------------------- repair jobs


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path) -> Any:
    store = LocalRawStore(clean_db, tmp_path)
    router = official_router(store)

    def _run(name: str, **params: Any) -> JobRunResult:
        return run_job(
            name, params, engine=clean_db, rawstore=store, notifier=ConsoleNotifier(), router=router
        )

    return _run


def test_refetch_stock_prices_fills_a_missed_day(run: Any, clean_db: Engine) -> None:
    day = date(2026, 10, 16)  # the recorded daily tables
    with clean_db.begin() as conn:
        ids: dict[str, int] = dict(
            conn.execute(
                text(
                    "INSERT INTO stocks (symbol, market, type, name, listed_date) VALUES "
                    "('2330', 'twse', 'stock', '台積電', '1994-09-05'), "
                    "('9999', 'twse', 'stock', 'other', '2000-01-01') RETURNING symbol, id"
                )
            ).all()
        )
        # The market traded that day (another stock has a bar), 2330's row is missing.
        conn.execute(
            text(
                "INSERT INTO prices_daily (stock_id, trade_date, close, source) "
                "VALUES (:s, :d, 10, 'test')"
            ),
            {"s": ids["9999"], "d": day},
        )
        assert stock_missing_days(conn, ids["2330"], day, day) == [day]

    result = run("refetch_stock_prices", symbol="2330", days=3650)
    assert result.status == "succeeded", result.error
    assert "補上 1 天" in (result.message or "")
    with clean_db.connect() as conn:
        assert stock_missing_days(conn, ids["2330"], day, day) == []
    again = run("refetch_stock_prices", symbol="2330", days=3650)
    assert again.status == "skipped"


def test_refetch_stock_prices_needs_a_known_symbol(run: Any) -> None:
    result = run("refetch_stock_prices", symbol="0000")
    assert result.status == "failed"
    assert "找不到" in (result.error or "")
