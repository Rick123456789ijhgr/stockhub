import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

export type FundamentalsStatus = {
  companies: number;
  statementsFetched: number;
  revenueFetched: number;
  computed: number;
  latestQuarter: string | null;
  latestQuarterCompanies: number;
  latestRevenueMonth: string | null;
  latestRevenueCompanies: number;
  quarantinePending: number;
  backfill: { id: string; startedAt: string; done: number; total: number; symbol: string | null } | null;
};

/** Coverage of statements and revenue, plus a running backfill_fundamentals (for /status). */
export async function getFundamentalsStatus(db: Kysely<DB>): Promise<FundamentalsStatus> {
  const [totals, run] = await Promise.all([
    sql<Omit<FundamentalsStatus, "backfill">>`
      WITH official AS (
        SELECT max(period_end) AS q FROM financials WHERE source IN ('twse', 'tpex')),
      latest_month AS (SELECT max(revenue_month) AS m FROM monthly_revenue)
      SELECT
        (SELECT count(*) FROM stocks WHERE type = 'stock'
          AND (delisted_date IS NULL OR delisted_date >= '2013-01-01'))::int AS companies,
        (SELECT count(DISTINCT stock_id) FROM financial_fetch_state
          WHERE dataset = 'IS')::int AS "statementsFetched",
        (SELECT count(DISTINCT stock_id) FROM financial_fetch_state
          WHERE dataset = 'monthly_revenue')::int AS "revenueFetched",
        (SELECT count(DISTINCT stock_id) FROM fundamentals_quarterly)::int AS computed,
        (SELECT q::text FROM official) AS "latestQuarter",
        (SELECT count(DISTINCT stock_id) FROM financials, official
          WHERE source IN ('twse', 'tpex') AND period_end = official.q)::int
          AS "latestQuarterCompanies",
        (SELECT m::text FROM latest_month) AS "latestRevenueMonth",
        (SELECT count(*) FROM monthly_revenue, latest_month
          WHERE revenue_month = latest_month.m)::int AS "latestRevenueCompanies",
        (SELECT count(*) FROM financials_quarantine WHERE resolved_at IS NULL)::int
          AS "quarantinePending"
    `.execute(db),
    db
      .selectFrom("job_runs")
      .select(["id", "started_at", "checkpoint"])
      .where("job_name", "=", "backfill_fundamentals")
      .where("status", "=", "running")
      .orderBy("started_at", "desc")
      .limit(1)
      .executeTakeFirst(),
  ]);
  const checkpoint = (run?.checkpoint ?? {}) as { done?: number; total?: number; symbol?: string };
  return {
    ...totals.rows[0],
    backfill: run
      ? {
          id: String(run.id),
          startedAt: run.started_at.toISOString(),
          done: checkpoint.done ?? 0,
          total: checkpoint.total ?? 0,
          symbol: checkpoint.symbol ?? null,
        }
      : null,
  };
}

export type QuarantinedStatement = {
  id: string;
  symbol: string;
  name: string;
  periodEnd: string;
  statement: "IS" | "BS" | "CF";
  source: string;
  reasons: string[];
  createdAt: string;
  items: { itemCode: string; value: string }[];
};

export async function listQuarantinedStatements(
  db: Kysely<DB>,
  limit = 50,
): Promise<QuarantinedStatement[]> {
  const result = await sql<{
    id: string;
    symbol: string;
    name: string;
    period_end: string;
    statement: "IS" | "BS" | "CF";
    source: string;
    reasons: string[];
    created_at: Date;
    payload: { item_code: string; value: string }[];
  }>`
    SELECT q.id::text, s.symbol, s.name, q.period_end::text, q.statement, q.source, q.reasons,
           q.created_at, q.payload
    FROM financials_quarantine q JOIN stocks s ON s.id = q.stock_id
    WHERE q.resolved_at IS NULL ORDER BY q.created_at DESC, q.id DESC LIMIT ${limit}
  `.execute(db);
  return result.rows.map((r) => ({
    id: r.id,
    symbol: r.symbol,
    name: r.name,
    periodEnd: r.period_end,
    statement: r.statement,
    source: r.source,
    reasons: r.reasons,
    createdAt: r.created_at.toISOString(),
    items: r.payload.map((i) => ({ itemCode: i.item_code, value: i.value })),
  }));
}

export type QuarantineDecision = "accept" | "reject";

/**
 * accept = write the statement into financials as received (each item as the next revision
 * of its source), reject = discard it. Audited as financials.quarantine_accept / _reject.
 * compute_fundamentals picks the company up on its next run.
 */
export async function resolveQuarantinedStatement(
  db: Kysely<DB>,
  id: string,
  decision: QuarantineDecision,
  actor: string,
): Promise<boolean> {
  return db.transaction().execute(async (trx) => {
    const row = await sql<{ symbol: string; period_end: string; statement: string }>`
      SELECT s.symbol, q.period_end::text, q.statement FROM financials_quarantine q
      JOIN stocks s ON s.id = q.stock_id
      WHERE q.id = ${id}::bigint AND q.resolved_at IS NULL FOR UPDATE OF q
    `.execute(trx);
    if (row.rows.length === 0) return false;
    if (decision === "accept") {
      await sql`
        INSERT INTO financials (stock_id, period_end, period_type, statement, item_code, value,
                                basis, source, revision, raw_object_id)
        SELECT q.stock_id, q.period_end, 'Q', q.statement, i->>'item_code',
               (i->>'value')::numeric, i->>'basis', q.source,
               coalesce((SELECT max(f.revision) + 1 FROM financials f
                         WHERE f.stock_id = q.stock_id AND f.period_end = q.period_end
                           AND f.statement = q.statement AND f.item_code = i->>'item_code'
                           AND f.source = q.source), 0),
               q.raw_object_id
        FROM financials_quarantine q, jsonb_array_elements(q.payload) i
        WHERE q.id = ${id}::bigint
      `.execute(trx);
    }
    await sql`
      UPDATE financials_quarantine SET resolved_at = now(),
        resolution = ${decision === "accept" ? "accepted" : "rejected"}
      WHERE id = ${id}::bigint
    `.execute(trx);
    const target = row.rows[0];
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: decision === "accept" ? "financials.quarantine_accept" : "financials.quarantine_reject",
        target: target.symbol,
        detail: JSON.stringify({ quarantineId: id, periodEnd: target.period_end, statement: target.statement }),
      })
      .execute();
    return true;
  });
}
