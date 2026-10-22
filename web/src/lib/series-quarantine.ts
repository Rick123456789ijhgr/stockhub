import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

export type QuarantinedObservation = {
  id: string;
  code: string;
  name: string;
  obsDate: string;
  source: string;
  reasons: string[];
  createdAt: string;
  payload: unknown;
  /** Last stored value before the date, for comparison. */
  previous: number | null;
};

export async function countQuarantinedObservations(db: Kysely<DB>): Promise<number> {
  const row = await db
    .selectFrom("market_series_quarantine")
    .select(sql<number>`count(*)::int`.as("n"))
    .where("resolved_at", "is", null)
    .executeTakeFirst();
  return row?.n ?? 0;
}

export async function listQuarantinedObservations(
  db: Kysely<DB>,
  limit = 200,
): Promise<QuarantinedObservation[]> {
  const rows = await sql<{
    id: string;
    code: string;
    name: string;
    obs_date: string;
    source: string;
    reasons: string[];
    created_at: Date;
    payload: unknown;
    previous: string | null;
  }>`
    SELECT q.id::text, q.series_code AS code, s.name, q.obs_date, q.source, q.reasons, q.created_at,
           q.payload,
           (SELECT v.value FROM market_series_values v WHERE v.series_code = q.series_code
              AND v.obs_date < q.obs_date ORDER BY v.obs_date DESC LIMIT 1) AS previous
    FROM market_series_quarantine q JOIN market_series s ON s.code = q.series_code
    WHERE q.resolved_at IS NULL
    ORDER BY q.created_at DESC, q.obs_date DESC
    LIMIT ${limit}
  `.execute(db);
  return rows.rows.map((r) => ({
    id: r.id,
    code: r.code,
    name: r.name,
    obsDate: String(r.obs_date),
    source: r.source,
    reasons: r.reasons,
    createdAt: r.created_at.toISOString(),
    payload: r.payload,
    previous: r.previous === null ? null : Number(r.previous),
  }));
}

/** Accept (write the observation as received) or reject a quarantined value; audited. */
export async function resolveQuarantinedObservation(
  db: Kysely<DB>,
  id: string,
  decision: "accept" | "reject",
  actor: string,
): Promise<boolean> {
  return db.transaction().execute(async (trx) => {
    const found = await sql<{ code: string; obs_date: string }>`
      SELECT series_code AS code, obs_date::text FROM market_series_quarantine
      WHERE id = ${id}::bigint AND resolved_at IS NULL FOR UPDATE
    `.execute(trx);
    const target = found.rows[0];
    if (!target) return false;
    if (decision === "accept") {
      await sql`
        INSERT INTO market_series_values (series_code, obs_date, open, high, low, value, label, source,
                                          raw_object_id)
        SELECT q.series_code, q.obs_date, (q.payload->>'open')::numeric, (q.payload->>'high')::numeric,
               (q.payload->>'low')::numeric, (q.payload->>'value')::numeric, q.payload->>'label', q.source,
               q.raw_object_id
        FROM market_series_quarantine q WHERE q.id = ${id}::bigint
        ON CONFLICT (series_code, obs_date) DO UPDATE SET open = excluded.open, high = excluded.high,
          low = excluded.low, value = excluded.value, label = excluded.label, source = excluded.source,
          raw_object_id = excluded.raw_object_id, fetched_at = now()
      `.execute(trx);
    }
    await sql`
      UPDATE market_series_quarantine SET resolved_at = now(),
        resolution = ${decision === "accept" ? "accepted" : "rejected"}
      WHERE id = ${id}::bigint
    `.execute(trx);
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: decision === "accept" ? "markets.quarantine_accept" : "markets.quarantine_reject",
        target: target.code,
        detail: JSON.stringify({ quarantineId: id, obsDate: target.obs_date }),
      })
      .execute();
    return true;
  });
}
