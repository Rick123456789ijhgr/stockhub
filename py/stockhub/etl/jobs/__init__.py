"""Scheduled jobs. Importing this package registers every built-in job."""

from stockhub.etl.jobs import freshness_check, heartbeat, market_data
from stockhub.etl.jobs.base import (
    Job,
    JobContext,
    JobError,
    JobOutcome,
    JobRunResult,
    register_job,
    registered_jobs,
    run_job,
)

__all__ = [
    "Job",
    "JobContext",
    "JobError",
    "JobOutcome",
    "JobRunResult",
    "freshness_check",
    "heartbeat",
    "market_data",
    "register_job",
    "registered_jobs",
    "run_job",
]
