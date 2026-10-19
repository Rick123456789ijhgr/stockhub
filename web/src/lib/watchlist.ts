import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import { loadMarks, type MarkInfo } from "@/lib/portfolio-data";
import type { Market } from "@/lib/stocks";

export type WatchItem = {
  symbol: string;
  name: string;
  market: Market;
  type: "stock" | "etf";
  delistedDate: string | null;
  note: string | null;
  position: number;
  addedAt: string;
  mark: MarkInfo | null;
};

/** The watchlist in custom order, each stock with its latest quote or close. */
export async function listWatchlist(db: Kysely<DB>): Promise<WatchItem[]> {
  const rows = await db
    .selectFrom("watchlist as w")
    .innerJoin("stocks as s", "s.id", "w.stock_id")
    .select([
      sql<string>`s.id::text`.as("id"),
      "s.symbol",
      "s.name",
      "s.market",
      "s.type",
      "s.delisted_date as delistedDate",
      "w.note",
      "w.position",
      "w.added_at as addedAt",
    ])
    .orderBy("w.position")
    .orderBy("w.added_at")
    .execute();
  const marks = await loadMarks(db, rows.map((r) => r.id));
  return rows.map(({ id, ...r }) => ({
    ...r,
    market: r.market as Market,
    type: r.type as WatchItem["type"],
    addedAt: r.addedAt.toISOString(),
    mark: marks[id] ?? null,
  }));
}

const MAX_NOTE = 500;

/** Set (or clear) a watchlist note; audited. False when the stock is not on the list. */
export async function setWatchNote(
  db: Kysely<DB>,
  symbol: string,
  note: string | null,
  actor: string,
): Promise<boolean> {
  const value = note?.trim() ? note.trim().slice(0, MAX_NOTE) : null;
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .selectFrom("watchlist as w")
      .innerJoin("stocks as s", "s.id", "w.stock_id")
      .select(["w.stock_id", "w.note"])
      .where("s.symbol", "=", symbol)
      .executeTakeFirst();
    if (!row) return false;
    if (row.note === value) return true;
    await trx.updateTable("watchlist").set({ note: value }).where("stock_id", "=", row.stock_id).execute();
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: "watchlist.note",
        target: symbol,
        detail: JSON.stringify({ before: row.note, after: value }),
      })
      .execute();
    return true;
  });
}

/**
 * Store a custom order: `symbols` first in the given order, anything not named keeps its
 * relative order after them. Audited when the order changes.
 */
export async function reorderWatchlist(
  db: Kysely<DB>,
  symbols: string[],
  actor: string,
): Promise<void> {
  await db.transaction().execute(async (trx) => {
    const rows = await trx
      .selectFrom("watchlist as w")
      .innerJoin("stocks as s", "s.id", "w.stock_id")
      .select(["w.stock_id", "s.symbol"])
      .orderBy("w.position")
      .orderBy("w.added_at")
      .execute();
    const rank = new Map(symbols.map((s, i) => [s, i]));
    const before = rows.map((r) => r.symbol);
    const after = [...rows].sort(
      (a, b) =>
        (rank.get(a.symbol) ?? symbols.length) - (rank.get(b.symbol) ?? symbols.length) ||
        before.indexOf(a.symbol) - before.indexOf(b.symbol),
    );
    if (after.every((r, i) => r.symbol === before[i])) return;
    for (const [i, r] of after.entries()) {
      await trx.updateTable("watchlist").set({ position: i + 1 }).where("stock_id", "=", r.stock_id).execute();
    }
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: "watchlist.reorder",
        target: null,
        detail: JSON.stringify({ before, after: after.map((r) => r.symbol) }),
      })
      .execute();
  });
}
