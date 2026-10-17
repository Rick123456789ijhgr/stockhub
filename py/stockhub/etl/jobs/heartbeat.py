"""heartbeat: exercise the whole pipeline (job_runs -> RawStore -> raw_objects) without network."""

from __future__ import annotations

from typing import ClassVar

from stockhub.etl.jobs.base import Job, JobContext, JobOutcome, register_job


@register_job
class HeartbeatJob(Job):
    name: ClassVar[str] = "heartbeat"
    description: ClassVar[str] = "Write a small raw object to verify DB, RawStore and job_runs"

    def run(self, ctx: JobContext) -> JobOutcome:
        # Deterministic per date: a rerun for the same date stores nothing new.
        payload = {"job": self.name, "date": ctx.params["date"]}
        obj = ctx.rawstore.put("stockhub", "heartbeat", payload, params=ctx.params)
        ctx.add_rows(1 if obj.created else 0)
        return JobOutcome()
