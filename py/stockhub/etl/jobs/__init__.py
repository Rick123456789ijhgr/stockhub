"""Scheduled jobs. Importing this package registers every built-in job."""

from stockhub.etl.jobs import (
    alerts,
    corporate_actions,
    etf_delistings,
    financials,
    freshness_check,
    heartbeat,
    market_data,
    previews,
    quotes,
)
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
    "alerts",
    "corporate_actions",
    "etf_delistings",
    "financials",
    "freshness_check",
    "heartbeat",
    "market_data",
    "previews",
    "quotes",
    "register_job",
    "registered_jobs",
    "run_job",
]
