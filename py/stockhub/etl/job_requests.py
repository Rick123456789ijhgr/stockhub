"""Run jobs the website queued in job_requests, oldest first, one at a time.

The site starts `python -m stockhub.etl drain-requests` right after queueing (locally), and
etl-daily runs it too, so a request made where nothing can be started (e.g. Vercel) still
runs with the next scheduled job. A session-level advisory lock keeps one drainer at a time;
a second one exits at once, and the running one re-checks the queue after releasing its
lock so a request queued at that moment is not left behind.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, text

from stockhub.common.timeutil import utcnow
from stockhub.etl.jobs.base import JobAlreadyRunningError, JobRunResult, UnknownJobError

log = logging.getLogger(__name__)

LOCK_KEY = 0x5354_4B48_5245_51  # "STKHREQ"
STALE_AFTER = timedelta(hours=3)
"""A request still 'running' after this lost its drainer (process killed)."""

RunJob = Callable[[str, dict[str, Any]], JobRunResult]


def _claim(engine: Engine) -> tuple[int, str, dict[str, Any]] | None:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "UPDATE job_requests SET status = 'running', started_at = now() WHERE id = ("
                "  SELECT id FROM job_requests WHERE status = 'queued' "
                "  ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) "
                "RETURNING id, job_name, params"
            )
        ).first()
    return (int(row.id), row.job_name, dict(row.params)) if row else None


def _finish(
    engine: Engine, request_id: int, status: str, run_id: int | None, message: str | None
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE job_requests SET status = :status, finished_at = now(), run_id = :run, "
                "message = :message WHERE id = :id"
            ),
            {"status": status, "run": run_id, "message": message, "id": request_id},
        )


def abandon_stale(engine: Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "UPDATE job_requests SET status = 'failed', finished_at = now(), "
                "message = '執行中斷（程式被關閉？），請重新送出' "
                "WHERE status = 'running' AND started_at < :cutoff"
            ),
            {"cutoff": utcnow() - STALE_AFTER},
        ).rowcount


def _pending(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM job_requests WHERE status = 'queued')")
            ).scalar_one()
        )


def drain(engine: Engine, run: RunJob) -> int:
    """Run queued requests until none is left; returns how many ran (0 if another drainer
    holds the lock)."""
    done = 0
    while True:
        with engine.connect() as lock_conn:
            got = lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
            ).scalar_one()
            lock_conn.commit()
            if not got:
                return done
            try:
                abandon_stale(engine)
                while (claimed := _claim(engine)) is not None:
                    request_id, job, params = claimed
                    done += 1
                    _run_one(engine, run, request_id, job, params)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                lock_conn.commit()
        if not _pending(engine):
            return done


def _run_one(
    engine: Engine, run: RunJob, request_id: int, job: str, params: dict[str, Any]
) -> None:
    log.info("request #%d: %s %s", request_id, job, params)
    try:
        result = run(job, params)
    except (UnknownJobError, JobAlreadyRunningError) as exc:
        _finish(engine, request_id, "failed", None, str(exc))
        return
    except Exception as exc:  # config errors and the like: record, keep draining
        log.exception("request #%d failed", request_id)
        _finish(engine, request_id, "failed", None, f"{type(exc).__name__}: {exc}")
        return
    message = result.error if result.status == "failed" else result.message
    _finish(engine, request_id, result.status, result.run_id, (message or "")[:2000] or None)
