import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

export type AlertItem = {
  id: string;
  kind: string;
  symbol: string;
  tradeDate: string;
  severity: string;
  title: string;
  createdAt: string;
  change: number | null;
  threshold: number | null;
};

/** Newest alerts first (written by the Python alert checks). */
export async function listRecentAlerts(db: Kysely<DB>, limit = 10): Promise<AlertItem[]> {
  const rows = await db
    .selectFrom("alerts as a")
    .innerJoin("stocks as s", "s.id", "a.stock_id")
    .select([
      sql<string>`a.id::text`.as("id"),
      "a.kind",
      "s.symbol",
      "a.trade_date as tradeDate",
      "a.severity",
      "a.title",
      "a.created_at as createdAt",
      sql<number | null>`(a.detail->>'change')::float8`.as("change"),
      sql<number | null>`(a.detail->>'threshold')::float8`.as("threshold"),
    ])
    .orderBy("a.created_at", "desc")
    .limit(limit)
    .execute();
  return rows.map((r) => ({ ...r, createdAt: r.createdAt.toISOString() }));
}
