from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import Engine, text

from stockhub.common.db import get_engine, upsert
from stockhub.common.notifier import Notifier, Severity
from stockhub.common.rawstore import LocalRawStore
from stockhub.common.settings import get_settings
from stockhub.common.timeutil import taipei_today
from stockhub.etl.__main__ import main
from stockhub.etl.jobs.base import (
    Job,
    JobAlreadyRunningError,
    JobContext,
    JobOutcome,
    JobRunResult,
    UnknownJobError,
    register_job,
    run_job,
    unregister_job,
)


class RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Severity]] = []

    def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
        self.sent.append((subject, body, severity))


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def run(clean_db: Engine, tmp_path: Path, notifier: RecordingNotifier) -> Any:
    store = LocalRawStore(clean_db, tmp_path)

    def _run(name: str, params: dict[str, Any] | None = None, **kwargs: Any) -> JobRunResult:
        return run_job(name, params, engine=clean_db, rawstore=store, notifier=notifier, **kwargs)

    return _run


def _rows(engine: Engine, sql: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql)).all())


# ----------------------------------------------------------------------------- heartbeat


def test_heartbeat_records_run_and_is_idempotent(run: Any, clean_db: Engine) -> None:
    first = run("heartbeat", {"date": "2026-10-16"})
    second = run("heartbeat", {"date": "2026-10-16"})

    assert (first.status, first.rows_written) == ("succeeded", 1)
    assert (second.status, second.rows_written) == ("succeeded", 0)
    runs = _rows(
        clean_db,
        "SELECT status, rows_written, params->>'date', \"trigger\", finished_at IS NOT NULL "
        "FROM job_runs ORDER BY id",
    )
    assert runs == [
        ("succeeded", 1, "2026-10-16", "manual", True),
        ("succeeded", 0, "2026-10-16", "manual", True),
    ]
    assert _rows(clean_db, "SELECT dataset FROM raw_objects") == [("heartbeat",)]


def test_date_defaults_to_taipei_today(run: Any) -> None:
    assert run("heartbeat").params == {"date": taipei_today().isoformat()}


def test_unknown_job(run: Any) -> None:
    with pytest.raises(UnknownJobError, match="available: freshness_check, heartbeat"):
        run("nope")


# ----------------------------------------------------------------------------- freshness_check


def _add_price(engine: Engine, trade_date: str) -> None:
    with engine.begin() as conn:
        stock_id = conn.execute(
            text(
                "INSERT INTO stocks (symbol, market, type, name, listed_date) "
                "VALUES ('2330', 'twse', 'stock', 'TSMC', '1994-09-05') "
                "ON CONFLICT (symbol, listed_date) DO UPDATE SET name = excluded.name "
                "RETURNING id"
            )
        ).scalar_one()
        upsert(
            conn,
            "prices_daily",
            [{"stock_id": stock_id, "trade_date": trade_date, "close": 1000, "source": "test"}],
            ["stock_id", "trade_date"],
        )


def test_freshness_empty_table_is_stale(run: Any, notifier: RecordingNotifier) -> None:
    result = run("freshness_check", {"date": "2026-10-14"})  # Wed -> expects Tue 10-13
    assert result.status == "failed"
    assert result.error == "資料落後：\nprices_daily：最新 無資料，應至少為 2026-10-13"
    assert len(notifier.sent) == 1
    subject, body, severity = notifier.sent[0]
    assert (subject, severity) == ("任務失敗：freshness_check", "critical")
    assert "應至少為 2026-10-13" in body


def test_freshness_up_to_date(run: Any, clean_db: Engine, notifier: RecordingNotifier) -> None:
    _add_price(clean_db, "2026-10-13")
    assert run("freshness_check", {"date": "2026-10-14"}).status == "succeeded"
    # Monday checks against the previous Friday.
    _add_price(clean_db, "2026-10-16")
    assert run("freshness_check", {"date": "2026-10-19"}).status == "succeeded"
    assert notifier.sent == []


def test_consecutive_failures_send_one_email_then_recovery(
    run: Any, clean_db: Engine, notifier: RecordingNotifier
) -> None:
    run("freshness_check", {"date": "2026-10-14"})
    run("freshness_check", {"date": "2026-10-14"})
    run("freshness_check", {"date": "2026-10-15"})  # other params, same streak
    assert [s[0] for s in notifier.sent] == ["任務失敗：freshness_check"]

    _add_price(clean_db, "2026-10-14")
    assert run("freshness_check", {"date": "2026-10-15"}).status == "succeeded"
    assert [s[0] for s in notifier.sent] == [
        "任務失敗：freshness_check",
        "任務恢復：freshness_check",
    ]

    run("freshness_check", {"date": "2026-10-20"})  # a new streak alerts again
    assert len(notifier.sent) == 3


# ----------------------------------------------------------------------------- checkpoints


class CounterJob(Job):
    """Writes items 0..4 one by one, checkpointing after each; can crash on purpose."""

    name: ClassVar[str] = "test_counter"
    description: ClassVar[str] = "test only"
    uses_date: ClassVar[bool] = False

    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at = fail_at
        self.processed: list[int] = []

    def run(self, ctx: JobContext) -> JobOutcome:
        start = (ctx.checkpoint or {}).get("next", 0)
        for i in range(start, 5):
            if i == self.fail_at:
                raise RuntimeError(f"crash at item {i}")
            with ctx.engine.begin() as conn:
                ctx.add_rows(upsert(conn, "settings", [{"key": f"item{i}", "value": i}], ["key"]))
            self.processed.append(i)
            ctx.save_checkpoint({"next": i + 1})
        return JobOutcome()


@pytest.fixture
def counter_job() -> Iterator[None]:
    register_job(CounterJob)
    yield
    unregister_job(CounterJob.name)


@pytest.mark.usefixtures("counter_job")
def test_failed_run_resumes_from_checkpoint(run: Any, clean_db: Engine) -> None:
    crashing = CounterJob(fail_at=3)
    first = run("test_counter", job_factory=lambda cls: crashing)
    assert (first.status, first.rows_written, crashing.processed) == ("failed", 3, [0, 1, 2])
    assert "RuntimeError: crash at item 3" in (first.error or "")

    resumed = CounterJob()
    second = run("test_counter", job_factory=lambda cls: resumed)
    assert second.resumed_from == {"next": 3}
    assert (second.status, second.rows_written, resumed.processed) == ("succeeded", 2, [3, 4])

    # After a success the next run starts over, and idempotent writes change nothing.
    fresh = CounterJob()
    third = run("test_counter", job_factory=lambda cls: fresh)
    assert (third.resumed_from, third.rows_written, fresh.processed) == (None, 0, [0, 1, 2, 3, 4])

    assert _rows(clean_db, "SELECT count(*) FROM settings") == [(5,)]
    assert _rows(clean_db, "SELECT status, checkpoint FROM job_runs ORDER BY id") == [
        ("failed", {"next": 3}),
        ("succeeded", None),
        ("succeeded", None),
    ]


# ----------------------------------------------------------------------------- concurrency


def _insert_running(engine: Engine, age: timedelta) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                'INSERT INTO job_runs (job_name, params, "trigger", started_at) VALUES '
                "('heartbeat', '{\"date\": \"2026-10-16\"}', 'schedule', now() - :age)"
            ),
            {"age": age},
        )


def test_same_params_cannot_run_twice(run: Any, clean_db: Engine) -> None:
    _insert_running(clean_db, timedelta(minutes=5))
    with pytest.raises(JobAlreadyRunningError):
        run("heartbeat", {"date": "2026-10-16"})
    assert run("heartbeat", {"date": "2026-10-17"}).status == "succeeded"


def test_stale_running_row_is_abandoned(run: Any, clean_db: Engine) -> None:
    _insert_running(clean_db, timedelta(hours=2))
    assert run("heartbeat", {"date": "2026-10-16"}).status == "succeeded"
    stale = _rows(clean_db, "SELECT status, error FROM job_runs ORDER BY id LIMIT 1")[0]
    assert stale.status == "failed"
    assert stale.error.startswith("abandoned")


def test_broken_notifier_does_not_change_outcome(clean_db: Engine, tmp_path: Path) -> None:
    class Exploding(Notifier):
        def send(self, subject: str, body: str, severity: Severity = "warning") -> None:
            raise OSError("smtp down")

    result = run_job(
        "freshness_check",
        {"date": "2026-10-14"},
        engine=clean_db,
        rawstore=LocalRawStore(clean_db, tmp_path),
        notifier=Exploding(),
    )
    assert result.status == "failed"
    assert _rows(clean_db, "SELECT status FROM job_runs") == [("failed",)]


# ----------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, test_database_url: str, tmp_path: Path, clean_db: Engine
) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("RAWSTORE_BACKEND", "local")
    monkeypatch.setenv("RAWSTORE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("NOTIFIER", "console")
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_cli_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "heartbeat" in out
    assert "freshness_check" in out


@pytest.mark.usefixtures("cli_env")
def test_cli_run_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "heartbeat", "--date", "2026-10-16", "--trigger", "schedule"]) == 0
    assert "heartbeat #1 succeeded rows_written=1" in capsys.readouterr().out
    assert main(["run", "freshness_check", "--date", "2026-10-16"]) == 1
    assert main(["run", "nope"]) == 2
    with pytest.raises(SystemExit):
        main(["run", "heartbeat", "--date", "16/10/2026"])
