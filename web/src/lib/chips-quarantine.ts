import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

export type ChipDataset = "institutional" | "margin" | "foreign_holdings" | "distribution";

export type QuarantinedChip = {
  id: string;
  dataset: ChipDataset;
  symbol: string;
  name: string;
  tradeDate: string;
  source: string;
  reasons: string[];
  createdAt: string;
  payload: unknown;
};

export async function countQuarantinedChips(db: Kysely<DB>): Promise<number> {
  const row = await db
    .selectFrom("chip_quarantine")
    .select(sql<number>`count(*)::int`.as("n"))
    .where("resolved_at", "is", null)
    .executeTakeFirst();
  return row?.n ?? 0;
}

export async function listQuarantinedChips(db: Kysely<DB>, limit = 200): Promise<QuarantinedChip[]> {
  const rows = await db
    .selectFrom("chip_quarantine as q")
    .innerJoin("stocks as s", "s.id", "q.stock_id")
    .select([
      sql<string>`q.id::text`.as("id"),
      "q.dataset",
      "s.symbol",
      "s.name",
      "q.trade_date",
      "q.source",
      "q.reasons",
      "q.created_at",
      "q.payload",
    ])
    .where("q.resolved_at", "is", null)
    .orderBy("q.created_at", "desc")
    .limit(limit)
    .execute();
  return rows.map((r) => ({
    id: r.id,
    dataset: r.dataset as ChipDataset,
    symbol: r.symbol,
    name: r.name,
    tradeDate: String(r.trade_date),
    source: r.source,
    reasons: r.reasons,
    createdAt: r.created_at.toISOString(),
    payload: r.payload,
  }));
}

/** Column lists written on accept; the payload is the provider model as received. */
const INSTITUTIONAL = [
  "foreign_buy", "foreign_sell", "foreign_net", "foreign_dealer_buy", "foreign_dealer_sell",
  "foreign_dealer_net", "trust_buy", "trust_sell", "trust_net", "dealer_buy", "dealer_sell",
  "dealer_net", "dealer_self_net", "dealer_hedge_net", "total_net",
];
const MARGIN = [
  "margin_buy", "margin_sell", "margin_redeem", "margin_balance", "margin_limit", "short_sell",
  "short_cover", "short_redeem", "short_balance", "short_limit", "offset_shares", "note",
];
const HOLDINGS = ["issued_shares", "foreign_shares", "foreign_ratio", "limit_ratio"];

async function acceptRow(trx: Kysely<DB>, id: string, table: string, columns: string[]) {
  const cols = sql.join(columns.map((c) => sql.ref(c)));
  // jsonb_populate_record casts every field to the table's column types.
  const values = sql.join(columns.map((c) => sql`r.${sql.ref(c)}`));
  const updates = sql.join(columns.map((c) => sql`${sql.ref(c)} = excluded.${sql.ref(c)}`));
  await sql`
    INSERT INTO ${sql.table(table)} (stock_id, trade_date, ${cols}, source)
    SELECT q.stock_id, q.trade_date, ${values}, q.source
    FROM chip_quarantine q, jsonb_populate_record(NULL::${sql.table(table)}, q.payload) r
    WHERE q.id = ${id}::bigint
    ON CONFLICT (stock_id, trade_date) DO UPDATE SET ${updates}, source = excluded.source
  `.execute(trx);
}

/** Accept (write to its table) or reject a quarantined chip row; audited. */
export async function resolveQuarantinedChip(
  db: Kysely<DB>,
  id: string,
  decision: "accept" | "reject",
  actor: string,
): Promise<boolean> {
  return db.transaction().execute(async (trx) => {
    const found = await sql<{ symbol: string; dataset: ChipDataset; trade_date: string }>`
      SELECT s.symbol, q.dataset, q.trade_date::text FROM chip_quarantine q
      JOIN stocks s ON s.id = q.stock_id
      WHERE q.id = ${id}::bigint AND q.resolved_at IS NULL FOR UPDATE OF q
    `.execute(trx);
    const target = found.rows[0];
    if (!target) return false;
    if (decision === "accept") {
      if (target.dataset === "institutional") await acceptRow(trx, id, "institutional_trades_daily", INSTITUTIONAL);
      if (target.dataset === "margin") await acceptRow(trx, id, "margin_daily", MARGIN);
      if (target.dataset === "foreign_holdings") await acceptRow(trx, id, "foreign_holdings_daily", HOLDINGS);
      if (target.dataset === "distribution") {
        await sql`
          INSERT INTO shareholding_distribution (stock_id, week_date, level, holders, shares, ratio, source)
          SELECT q.stock_id, q.trade_date, (l->>'level')::smallint, (l->>'holders')::int,
                 (l->>'shares')::bigint, (l->>'ratio')::numeric, q.source
          FROM chip_quarantine q, jsonb_array_elements(q.payload) l
          WHERE q.id = ${id}::bigint
          ON CONFLICT (stock_id, week_date, level) DO UPDATE SET holders = excluded.holders,
            shares = excluded.shares, ratio = excluded.ratio, source = excluded.source
        `.execute(trx);
      }
    }
    await sql`
      UPDATE chip_quarantine SET resolved_at = now(),
        resolution = ${decision === "accept" ? "accepted" : "rejected"}
      WHERE id = ${id}::bigint
    `.execute(trx);
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: decision === "accept" ? "chips.quarantine_accept" : "chips.quarantine_reject",
        target: target.symbol,
        detail: JSON.stringify({ quarantineId: id, dataset: target.dataset, tradeDate: target.trade_date }),
      })
      .execute();
    return true;
  });
}
