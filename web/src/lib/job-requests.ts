import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { JobRequestInput, RequestableJob } from "@/lib/job-request-input";

export type JobRequestStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

export type JobRequestRow = {
  id: string;
  job: RequestableJob;
  params: Record<string, string>;
  status: JobRequestStatus;
  requestedAt: string;
  finishedAt: string | null;
  message: string | null;
};

/**
 * Queue a request and audit it (`jobs.request`). The same job with the same params already
 * waiting or running is returned instead of queueing it twice.
 */
export async function enqueueJob(
  db: Kysely<DB>,
  input: JobRequestInput,
  actor: string,
): Promise<{ id: string; duplicate: boolean }> {
  const params = JSON.stringify(input.params);
  return db.transaction().execute(async (trx) => {
    const inserted = await sql<{ id: string }>`
      INSERT INTO job_requests (job_name, params, requested_by)
      VALUES (${input.job}, CAST(${params} AS jsonb), ${actor})
      ON CONFLICT (job_name, params) WHERE status IN ('queued', 'running') DO NOTHING
      RETURNING id::text AS id
    `.execute(trx);
    if (inserted.rows.length === 0) {
      const existing = await sql<{ id: string }>`
        SELECT id::text AS id FROM job_requests
        WHERE job_name = ${input.job} AND params = CAST(${params} AS jsonb)
          AND status IN ('queued', 'running')
      `.execute(trx);
      return { id: existing.rows[0]?.id ?? "", duplicate: true };
    }
    const id = inserted.rows[0].id;
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: "jobs.request",
        target: input.params.symbol ?? input.params.date ?? null,
        detail: JSON.stringify({ requestId: id, job: input.job, params: input.params }),
      })
      .execute();
    return { id, duplicate: false };
  });
}

/** Newest requests first, optionally only those about one symbol. */
export async function listJobRequests(
  db: Kysely<DB>,
  { limit = 10, symbol }: { limit?: number; symbol?: string } = {},
): Promise<JobRequestRow[]> {
  let query = db
    .selectFrom("job_requests")
    .select(["id", "job_name", "params", "status", "requested_at", "finished_at", "message"])
    .orderBy("id", "desc")
    .limit(Math.min(Math.max(limit, 1), 50));
  if (symbol) query = query.where(sql<boolean>`params->>'symbol' = ${symbol}`);
  const rows = await query.execute();
  return rows.map((r) => ({
    id: String(r.id),
    job: r.job_name as RequestableJob,
    params: (r.params ?? {}) as Record<string, string>,
    status: r.status as JobRequestStatus,
    requestedAt: r.requested_at.toISOString(),
    finishedAt: r.finished_at ? r.finished_at.toISOString() : null,
    message: r.message,
  }));
}

/** Days within the stock's listing on which the market traded but it has no bar. */
export async function getStockMissingDays(
  db: Kysely<DB>,
  stockId: string,
  from: string,
  to: string,
): Promise<string[]> {
  const result = await sql<{ d: string }>`
    SELECT d::text AS d FROM stock_missing_days(${stockId}::bigint, ${from}::date, ${to}::date) AS d
  `.execute(db);
  return result.rows.map((r) => r.d);
}
