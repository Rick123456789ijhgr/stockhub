import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { IntradayDay } from "@/lib/intraday";
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

/**
 * The latest sampled day of a stock (quotes_intraday, every 30 s round of poll_quotes), with
 * that day's reference price from quotes_latest when it is the same day.
 */
export async function getIntraday(db: Kysely<DB>, stockId: number): Promise<IntradayDay | null> {
  const id = String(stockId);
  const rows = await db
    .selectFrom("quotes_intraday as i")
    .leftJoin("quotes_latest as l", (join) =>
      join.onRef("l.stock_id", "=", "i.stock_id").onRef("l.trade_date", "=", "i.trade_date"),
    )
    .select(["i.trade_date as tradeDate", "i.sampled_at as sampledAt", "i.price", "l.prev_close as prevClose"])
    .where("i.stock_id", "=", id)
    .where("i.trade_date", "=", (eb) =>
      eb.selectFrom("quotes_intraday").select((e) => e.fn.max("trade_date").as("d")).where("stock_id", "=", id),
    )
    .orderBy("i.sampled_at")
    .execute();
  if (rows.length === 0) return null;
  return {
    tradeDate: rows[0].tradeDate,
    prevClose: rows[0].prevClose,
    points: rows.map((r) => ({ at: r.sampledAt.toISOString(), price: r.price })),
  };
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
