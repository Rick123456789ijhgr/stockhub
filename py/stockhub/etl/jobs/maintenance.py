"""cluster_tables: rewrite the per-stock tables in stock order (docs/DECISIONS.md D-117).

The daily jobs append every stock for one date together, so a stock's history ends up one
row per page and a first open of a stock reads hundreds of pages from disk. A plain CLUSTER
rewrites every table the migrations marked (`ALTER TABLE … CLUSTER ON`, stock-first index)
so a stock's rows sit together again. It takes an exclusive lock on each table while it
runs (minutes for prices_daily), so the job only runs outside trading and ETL hours unless
`force=true`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import ClassVar

from sqlalchemy import text

from stockhub.common.timeutil import TAIPEI, utcnow
from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job

log = logging.getLogger(__name__)

BUSY_START = 7
"""Weekday hour (Taipei) from which jobs and the site are busy: 07:30 markets, quotes, …"""
BUSY_END = (22, 30)
"""Weekday time (Taipei) after which the 21:30 chips job has finished."""


def in_maintenance_window(now: datetime) -> bool:
    """Weekends, and weekday nights outside 07:00～22:30 Taipei."""
    local = now.astimezone(TAIPEI)
    if local.weekday() >= 5:
        return True
    return local.hour < BUSY_START or (local.hour, local.minute) >= BUSY_END


@register_job
class ClusterTablesJob(Job):
    name: ClassVar[str] = "cluster_tables"
    description: ClassVar[str] = (
        "Rewrite the per-stock tables in stock order (CLUSTER), then ANALYZE"
    )
    uses_date: ClassVar[bool] = False
    timeout: ClassVar[timedelta] = timedelta(hours=2)

    def run(self, ctx: JobContext) -> JobOutcome:
        force = str(ctx.params.get("force", "")).lower() in {"1", "true", "yes"}
        if not force and not in_maintenance_window(utcnow()):
            return JobOutcome(
                status="skipped", message="trading or ETL hours; rerun with force=true"
            )
        # CLUSTER cannot run inside a transaction block.
        with ctx.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            tables = (
                conn.execute(
                    text(
                        """
                    SELECT c.relname FROM pg_index x JOIN pg_class c ON c.oid = x.indrelid
                    WHERE x.indisclustered ORDER BY c.relname
                    """
                    )
                )
                .scalars()
                .all()
            )
            for table in tables:
                started = time.monotonic()
                conn.execute(text(f'CLUSTER "{table}"'))
                conn.execute(text(f'ANALYZE "{table}"'))
                log.info("clustered %s in %.0f s", table, time.monotonic() - started)
        return JobOutcome(message=f"clustered {len(tables)} tables")
