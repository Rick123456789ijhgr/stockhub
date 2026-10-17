"""freshness_check: alert when daily data lags behind the previous trading day.

A stale dataset makes the run fail; run_job() then emails once per failure streak.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from sqlalchemy import text

from stockhub.common.trading_calendar import previous_trading_day
from stockhub.etl.jobs.base import Job, JobContext, JobError, JobOutcome, register_job

# dataset -> date column checked for freshness. Later milestones add their tables here.
DATASETS: dict[str, str] = {"prices_daily": "trade_date"}


@register_job
class FreshnessCheckJob(Job):
    name: ClassVar[str] = "freshness_check"
    description: ClassVar[str] = "Fail (and email) when prices_daily lags the previous trading day"

    def run(self, ctx: JobContext) -> JobOutcome:
        with ctx.engine.connect() as conn:
            expected = previous_trading_day(conn, ctx.run_date)
            stale: list[str] = []
            for table, column in DATASETS.items():
                latest: date | None = conn.execute(
                    text(f"SELECT max({column}) FROM {table}")  # noqa: S608 - constant names
                ).scalar_one()
                if latest is None or latest < expected:
                    shown = latest.isoformat() if latest else "無資料"
                    stale.append(f"{table}：最新 {shown}，應至少為 {expected.isoformat()}")
        if stale:
            raise JobError("資料落後：\n" + "\n".join(stale))
        return JobOutcome()
