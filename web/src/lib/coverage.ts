import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

import type { DayCoverage } from "./coverage-grid";

/**
 * Per calendar day: trading-day flag and bar counts per market. Aggregates all of
 * prices_daily on every request — fine at ~1M rows; precompute once multi-year history
 * makes /status slow.
 */
export async function getDayCoverage(db: Kysely<DB>, untilYear: number): Promise<DayCoverage[]> {
  const result = await sql<{ date: string; isTradingDay: boolean; twse: number; tpex: number }>`
    SELECT c.date::text AS date, c.is_trading_day AS "isTradingDay",
           coalesce(t.twse, 0)::int AS twse, coalesce(t.tpex, 0)::int AS tpex
    FROM trading_calendar c
    LEFT JOIN (
      SELECT p.trade_date,
             count(*) FILTER (WHERE s.market = 'twse') AS twse,
             count(*) FILTER (WHERE s.market = 'tpex') AS tpex
      FROM prices_daily p JOIN stocks s ON s.id = p.stock_id
      GROUP BY p.trade_date
    ) t ON t.trade_date = c.date
    WHERE c.date <= make_date(${untilYear}, 12, 31)
    ORDER BY c.date
  `.execute(db);
  return result.rows;
}

export type DataTotals = {
  bars: number;
  stocks: number;
  etfs: number;
  quarantinePending: number;
  rawObjects: number;
};

export async function getDataTotals(db: Kysely<DB>): Promise<DataTotals> {
  const result = await sql<DataTotals>`
    SELECT
      (SELECT count(*) FROM prices_daily)::int AS bars,
      (SELECT count(*) FROM stocks WHERE delisted_date IS NULL AND type = 'stock')::int AS stocks,
      (SELECT count(*) FROM stocks WHERE delisted_date IS NULL AND type = 'etf')::int AS etfs,
      (SELECT count(*) FROM prices_daily_quarantine WHERE resolved_at IS NULL)::int
        AS "quarantinePending",
      (SELECT count(*) FROM raw_objects)::int AS "rawObjects"
  `.execute(db);
  return result.rows[0];
}

export type RunningBackfill = {
  id: string;
  start: string;
  end: string;
  next: string | null;
  startedAt: string;
  tradingDays: string[];
};

/** In-flight backfill_prices runs with the trading days they cover. */
export async function getRunningBackfills(db: Kysely<DB>): Promise<RunningBackfill[]> {
  const runs = await db
    .selectFrom("job_runs")
    .select(["id", "params", "checkpoint", "started_at"])
    .where("job_name", "=", "backfill_prices")
    .where("status", "=", "running")
    .orderBy("started_at", "desc")
    .execute();

  const out: RunningBackfill[] = [];
  for (const run of runs) {
    const params = (run.params ?? {}) as Record<string, string | undefined>;
    const checkpoint = (run.checkpoint ?? {}) as Record<string, string | undefined>;
    // Same defaults as the job: end = today (Taipei), start = end - 365 days.
    const end = params.end ?? taipeiToday();
    const start = params.start ?? shiftDays(end, -365);
    const days = await db
      .selectFrom("trading_calendar")
      .select(sql<string>`date::text`.as("date"))
      .where("is_trading_day", "=", true)
      .where("date", ">=", start)
      .where("date", "<=", end)
      .orderBy("date")
      .execute();
    out.push({
      id: String(run.id),
      start,
      end,
      next: checkpoint.next ?? null,
      startedAt: run.started_at.toISOString(),
      tradingDays: days.map((d) => d.date),
    });
  }
  return out;
}

function taipeiToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei" }).format(new Date());
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export { taipeiToday };
