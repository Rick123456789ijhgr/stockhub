import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { LiveQuote } from "@/lib/market-hours";

/** The latest polled snapshot of a stock (written by the poll_quotes job), if any. */
export async function getLatestQuote(db: Kysely<DB>, stockId: number): Promise<LiveQuote | null> {
  const row = await db
    .selectFrom("quotes_latest")
    .select([
      "trade_date as tradeDate",
      "quote_time as quoteTime",
      "price",
      "open",
      "high",
      "low",
      "prev_close as prevClose",
      "volume",
      "bid",
      "ask",
    ])
    .where("stock_id", "=", String(stockId))
    .executeTakeFirst();
  if (!row) return null;
  return { ...row, quoteTime: row.quoteTime.toISOString(), volume: String(row.volume) };
}

export async function isWatched(db: Kysely<DB>, stockId: number): Promise<boolean> {
  const row = await db
    .selectFrom("watchlist")
    .select("stock_id")
    .where("stock_id", "=", String(stockId))
    .executeTakeFirst();
  return row !== undefined;
}

/** Add or remove a watchlist entry; manual changes are written to the audit log. */
export async function setWatched(
  db: Kysely<DB>,
  stock: { id: number; symbol: string },
  watched: boolean,
  actor: string,
): Promise<void> {
  await db.transaction().execute(async (trx) => {
    const changed = watched
      ? await trx
          .insertInto("watchlist")
          .values({
            stock_id: String(stock.id),
            position: sql<number>`(SELECT coalesce(max(position), 0) + 1 FROM watchlist)`,
          })
          .onConflict((oc) => oc.column("stock_id").doNothing())
          .executeTakeFirst()
      : await trx
          .deleteFrom("watchlist")
          .where("stock_id", "=", String(stock.id))
          .executeTakeFirst();
    const rows =
      "numInsertedOrUpdatedRows" in changed
        ? Number(changed.numInsertedOrUpdatedRows ?? 0)
        : Number(changed.numDeletedRows);
    if (rows === 0) return;
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: watched ? "watchlist.add" : "watchlist.remove",
        target: stock.symbol,
        detail: JSON.stringify({ stockId: stock.id }),
      })
      .execute();
  });
}
