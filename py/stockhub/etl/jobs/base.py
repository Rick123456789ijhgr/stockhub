"""Job framework: every scheduled task runs through run_job(), which records job_runs.

Guarantees:
- one job_runs row per execution, committed immediately (visible on /status while running);
- at most one in-flight run per (job, params); runs older than the job timeout are abandoned;
- a rerun with the same params resumes from the checkpoint of the latest run if that run failed;
- failures notify once per streak (consecutive failures of a job are merged), recovery notifies.
Jobs themselves must write idempotently (upsert / unique keys).
"""

from __future__ import annotations

import json
import logging
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from stockhub.common.notifier import Notifier
from stockhub.common.rawstore import RawStore
from stockhub.common.timeutil import taipei_today, utcnow

if TYPE_CHECKING:
    from stockhub.etl.providers.router import ProviderRouter

log = logging.getLogger(__name__)

Trigger = Literal["schedule", "manual"]
FinalStatus = Literal["succeeded", "failed", "skipped"]

MAX_ERROR_CHARS = 4000


class JobError(Exception):
    """Expected job failure: recorded without a traceback (e.g. stale data)."""


class JobAlreadyRunningError(RuntimeError):
    pass


class UnknownJobError(LookupError):
    pass


@dataclass
class JobContext:
    run_id: int
    job_name: str
    params: dict[str, Any]
    engine: Engine
    rawstore: RawStore
    notifier: Notifier
    checkpoint: dict[str, Any] | None
    """Checkpoint to resume from (None on a fresh run)."""
    rows_written: int = 0
    router: ProviderRouter | None = None
    """Provider access for jobs that fetch data (built by the CLI, injected in tests)."""

    def require_router(self) -> ProviderRouter:
        if self.router is None:
            raise JobError(f"job {self.job_name} needs a provider router")
        return self.router

    @property
    def run_date(self) -> date:
        return date.fromisoformat(self.params["date"])

    def add_rows(self, count: int) -> None:
        self.rows_written += count

    def save_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        """Persist progress now (own transaction), so a crash can resume from here."""
        self.checkpoint = checkpoint
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE job_runs SET checkpoint = CAST(:cp AS jsonb), rows_written = :rows "
                    "WHERE id = :id"
                ),
                {"cp": json.dumps(checkpoint), "rows": self.rows_written, "id": self.run_id},
            )


@dataclass(frozen=True)
class JobOutcome:
    """What a job returns; raising instead means failure."""

    status: Literal["succeeded", "skipped"] = "succeeded"
    message: str | None = None


@dataclass(frozen=True)
class JobRunResult:
    run_id: int
    job_name: str
    params: dict[str, Any]
    status: FinalStatus
    rows_written: int
    error: str | None = None
    resumed_from: dict[str, Any] | None = field(default=None)
    message: str | None = None
    """Summary from the job (e.g. rows per market), also logged."""


class Job(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    uses_date: ClassVar[bool] = True
    """When True, params always carry `date` (YYYY-MM-DD, Taipei); defaults to today."""
    timeout: ClassVar[timedelta] = timedelta(hours=1)
    """A running row older than this is considered abandoned."""

    @abstractmethod
    def run(self, ctx: JobContext) -> JobOutcome: ...


_JOBS: dict[str, type[Job]] = {}


def register_job[J: type[Job]](cls: J) -> J:
    existing = _JOBS.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"job name {cls.name!r} already registered by {existing}")
    _JOBS[cls.name] = cls
    return cls


def unregister_job(name: str) -> None:
    _JOBS.pop(name, None)


def registered_jobs() -> dict[str, type[Job]]:
    import stockhub.etl.jobs  # noqa: F401 - registers built-in jobs

    return dict(sorted(_JOBS.items()))


def normalize_params(job: type[Job], params: Mapping[str, Any], today: date) -> dict[str, Any]:
    out = {str(k): v for k, v in params.items()}
    if job.uses_date:
        out["date"] = date.fromisoformat(str(out.get("date") or today.isoformat())).isoformat()
    # Round-trip through JSON so the stored params equal what the job sees.
    return dict(sorted(json.loads(json.dumps(out, default=str)).items()))


def run_job(
    name: str,
    params: Mapping[str, Any] | None = None,
    trigger: Trigger = "manual",
    *,
    engine: Engine,
    rawstore: RawStore,
    notifier: Notifier,
    job_factory: Callable[[type[Job]], Job] | None = None,
    router: ProviderRouter | None = None,
) -> JobRunResult:
    jobs = registered_jobs()
    if name not in jobs:
        raise UnknownJobError(f"unknown job {name!r}; available: {', '.join(jobs)}")
    job_cls = jobs[name]
    job = (job_factory or (lambda cls: cls()))(job_cls)
    clean = normalize_params(job_cls, params or {}, taipei_today())
    params_json = json.dumps(clean)

    resume = _resume_checkpoint(engine, name, params_json)
    run_id = _start_run(engine, job_cls, params_json, trigger, resume)
    ctx = JobContext(run_id, name, clean, engine, rawstore, notifier, resume, router=router)
    log.info("job %s #%d started params=%s resume=%s", name, run_id, params_json, bool(resume))

    status: FinalStatus
    error: str | None = None
    message: str | None = None
    try:
        outcome = job.run(ctx)
        status = outcome.status
        message = outcome.message
        error = outcome.message if outcome.status == "skipped" else None
    except Exception as exc:
        status = "failed"
        if isinstance(exc, JobError):
            error = str(exc)
        else:
            error = "".join(traceback.format_exception(exc))[-MAX_ERROR_CHARS:]
        log.error("job %s #%d failed: %s", name, run_id, exc)

    previous = _previous_status(engine, name, run_id)
    _finish_run(engine, ctx, status, error)
    log.info("job %s #%d %s rows=%d %s", name, run_id, status, ctx.rows_written, message or "")
    _notify_transition(notifier, name, run_id, clean, status, error, previous)
    return JobRunResult(run_id, name, clean, status, ctx.rows_written, error, resume, message)


# ----------------------------------------------------------------------------- job_runs I/O


def _resume_checkpoint(engine: Engine, name: str, params_json: str) -> dict[str, Any] | None:
    """Checkpoint of the latest finished run with these params, if that run failed."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, checkpoint FROM job_runs WHERE job_name = :name "
                "AND params = CAST(:params AS jsonb) AND status <> 'running' "
                "ORDER BY started_at DESC, id DESC LIMIT 1"
            ),
            {"name": name, "params": params_json},
        ).first()
    if row is None or row.status != "failed" or row.checkpoint is None:
        return None
    return dict(row.checkpoint)


def _start_run(
    engine: Engine,
    job_cls: type[Job],
    params_json: str,
    trigger: Trigger,
    checkpoint: dict[str, Any] | None,
) -> int:
    insert = text(
        'INSERT INTO job_runs (job_name, params, "trigger", checkpoint) '
        "VALUES (:name, CAST(:params AS jsonb), :trigger, CAST(:cp AS jsonb)) RETURNING id"
    )
    values = {
        "name": job_cls.name,
        "params": params_json,
        "trigger": trigger,
        "cp": json.dumps(checkpoint) if checkpoint is not None else None,
    }
    for attempt in (1, 2):
        try:
            with engine.begin() as conn:
                return int(conn.execute(insert, values).scalar_one())
        except IntegrityError:
            if attempt == 2 or not _abandon_stale(engine, job_cls, params_json):
                raise JobAlreadyRunningError(
                    f"job {job_cls.name} is already running with params {params_json}"
                ) from None
    raise AssertionError("unreachable")  # pragma: no cover


def _abandon_stale(engine: Engine, job_cls: type[Job], params_json: str) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE job_runs SET status = 'failed', finished_at = now(), "
                "error = 'abandoned: still running after ' || :timeout || ' (process died?)' "
                "WHERE job_name = :name AND params = CAST(:params AS jsonb) "
                "AND status = 'running' AND started_at < :cutoff"
            ),
            {
                "name": job_cls.name,
                "params": params_json,
                "timeout": str(job_cls.timeout),
                "cutoff": utcnow() - job_cls.timeout,
            },
        )
    return result.rowcount > 0


def _previous_status(engine: Engine, name: str, run_id: int) -> str | None:
    with engine.connect() as conn:
        status: str | None = conn.execute(
            text(
                "SELECT status FROM job_runs WHERE job_name = :name AND id <> :id "
                "AND status IN ('succeeded', 'failed') ORDER BY started_at DESC, id DESC LIMIT 1"
            ),
            {"name": name, "id": run_id},
        ).scalar_one_or_none()
    return status


def _finish_run(engine: Engine, ctx: JobContext, status: FinalStatus, error: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE job_runs SET status = :status, finished_at = now(), "
                "rows_written = :rows, error = :error, checkpoint = CAST(:cp AS jsonb) "
                "WHERE id = :id"
            ),
            {
                "status": status,
                "rows": ctx.rows_written,
                "error": error,
                # A finished run needs no resume point.
                "cp": json.dumps(ctx.checkpoint) if status == "failed" and ctx.checkpoint else None,
                "id": ctx.run_id,
            },
        )


def _notify_transition(
    notifier: Notifier,
    name: str,
    run_id: int,
    params: dict[str, Any],
    status: FinalStatus,
    error: str | None,
    previous: str | None,
) -> None:
    try:
        if status == "failed" and previous != "failed":
            notifier.send(
                f"任務失敗：{name}",
                f"任務 {name}（job_runs #{run_id}）執行失敗。\n參數：{json.dumps(params)}\n\n"
                f"{error}\n\n同一任務在恢復成功前的後續失敗不會再寄通知；"
                "請到 /status 查看。",
                severity="critical",
            )
        elif status == "succeeded" and previous == "failed":
            notifier.send(
                f"任務恢復：{name}",
                f"任務 {name}（job_runs #{run_id}）已恢復成功。",
                severity="info",
            )
    except Exception:  # a broken notifier must not change the recorded job outcome
        log.exception("failed to send notification for job %s #%d", name, run_id)
