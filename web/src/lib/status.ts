import "server-only";

import type { Kysely } from "kysely";

import type { DB } from "@/lib/db";
import { summarizeError } from "@/lib/format";

export type JobRunStatus = "running" | "succeeded" | "failed" | "skipped";

export type JobRunRow = {
  id: string;
  jobName: string;
  status: JobRunStatus;
  trigger: string;
  params: unknown;
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
  rowsWritten: number;
  errorSummary: string | null;
};

export type DatasetFreshness = {
  dataset: string;
  label: string;
  latestDate: string | null;
};

export type StatusData = { jobRuns: JobRunRow[]; datasets: DatasetFreshness[] };

/** Datasets shown on /status; later milestones append their tables. */
const DATASETS = [{ dataset: "prices_daily", label: "日線價格" }] as const;

export async function getStatusData(db: Kysely<DB>, limit = 50): Promise<StatusData> {
  const [runs, prices] = await Promise.all([
    db
      .selectFrom("job_runs")
      .select([
        "id",
        "job_name",
        "status",
        "trigger",
        "params",
        "started_at",
        "finished_at",
        "rows_written",
        "error",
      ])
      .orderBy("started_at", "desc")
      .orderBy("id", "desc")
      .limit(limit)
      .execute(),
    db
      .selectFrom("prices_daily")
      .select((eb) => eb.fn.max("trade_date").as("latest"))
      .executeTakeFirst(),
  ]);

  return {
    jobRuns: runs.map((r) => ({
      id: String(r.id),
      jobName: r.job_name,
      status: r.status as JobRunStatus,
      trigger: r.trigger,
      params: r.params,
      startedAt: r.started_at.toISOString(),
      finishedAt: r.finished_at?.toISOString() ?? null,
      durationMs: r.finished_at ? r.finished_at.getTime() - r.started_at.getTime() : null,
      rowsWritten: r.rows_written,
      errorSummary: summarizeError(r.error),
    })),
    datasets: DATASETS.map((d) => ({ ...d, latestDate: prices?.latest ?? null })),
  };
}
