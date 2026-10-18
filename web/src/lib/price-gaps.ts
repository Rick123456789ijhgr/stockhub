import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { GapActionType, GapDecision } from "@/lib/price-gap-decision";

/** Written by compute_adj_factors for adjusted-price gaps no recorded event explains. */
const GAP_SOURCE = "derived:price-gap";
/** corporate_actions.source of hand-confirmed events; an imported event replaces them. */
const MANUAL_SOURCE = "manual";

export type PriceGap = {
  id: string;
  symbol: string;
  name: string | null;
  market: string | null;
  exDate: string;
  previousDate: string;
  previousClose: number;
  close: number;
  /** Adjusted close / previous adjusted close. */
  priceRatio: number;
  suggestion: { ratio: number; actionType: GapActionType; impliedMove: number } | null;
};

type GapPayload = {
  previous_date: string;
  previous_adjusted_close: string;
  adjusted_close: string;
  ratio: string;
  suggestion?: { ratio: string; action_type: GapActionType; implied_move: string };
};

/** Pending price-gap flags, ones with a suggested ratio first, then by date. */
export async function listPendingGaps(db: Kysely<DB>, limit = 200): Promise<PriceGap[]> {
  const rows = await db
    .selectFrom("corporate_actions_quarantine as q")
    .leftJoin("stocks as s", "s.id", "q.stock_id")
    .select(["q.id", "q.symbol", "q.ex_date", "q.payload", "s.name", "s.market"])
    .where("q.source", "=", GAP_SOURCE)
    .where("q.resolved_at", "is", null)
    .orderBy(sql`(q.payload ? 'suggestion')`, "desc")
    .orderBy("q.ex_date", "desc")
    .limit(limit)
    .execute();
  return rows.map((r) => {
    const p = r.payload as GapPayload;
    return {
      id: String(r.id),
      symbol: r.symbol,
      name: r.name,
      market: r.market,
      exDate: r.ex_date,
      previousDate: p.previous_date,
      previousClose: Number(p.previous_adjusted_close),
      close: Number(p.adjusted_close),
      priceRatio: Number(p.ratio),
      suggestion: p.suggestion
        ? {
            ratio: Number(p.suggestion.ratio),
            actionType: p.suggestion.action_type,
            impliedMove: Number(p.suggestion.implied_move),
          }
        : null,
    };
  });
}

export async function countPendingGaps(db: Kysely<DB>): Promise<number> {
  const row = await db
    .selectFrom("corporate_actions_quarantine")
    .select((eb) => eb.fn.countAll<string>().as("n"))
    .where("source", "=", GAP_SOURCE)
    .where("resolved_at", "is", null)
    .executeTakeFirstOrThrow();
  return Number(row.n);
}

/**
 * Confirm a gap as an event (adds a manual corporate action; adj_factor follows on the next
 * compute_adj_factors run) or dismiss it as a real price move. Returns false when the flag
 * does not exist or was already reviewed.
 */
export async function resolveGap(
  db: Kysely<DB>,
  id: string,
  decision: GapDecision,
  actor: string,
): Promise<boolean> {
  return db.transaction().execute(async (trx) => {
    const flag = await trx
      .updateTable("corporate_actions_quarantine")
      .set({
        resolved_at: new Date(),
        resolution: decision.kind === "confirm" ? "accepted" : "discarded",
      })
      .where("id", "=", id)
      .where("source", "=", GAP_SOURCE)
      .where("resolved_at", "is", null)
      .where("stock_id", "is not", null)
      .returning(["symbol", "stock_id", "ex_date"])
      .executeTakeFirst();
    if (!flag?.stock_id) return false;
    if (decision.kind === "confirm") {
      await trx
        .insertInto("corporate_actions")
        .values({
          stock_id: flag.stock_id,
          ex_date: flag.ex_date,
          action_type: decision.actionType,
          ratio: String(decision.ratio),
          source: MANUAL_SOURCE,
        })
        .onConflict((oc) =>
          oc
            .columns(["stock_id", "ex_date", "action_type"])
            .doUpdateSet({ ratio: String(decision.ratio) })
            .where("corporate_actions.source", "=", MANUAL_SOURCE),
        )
        .execute();
    }
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: decision.kind === "confirm" ? "price_gap.confirm" : "price_gap.dismiss",
        target: flag.symbol,
        detail: JSON.stringify({ flagId: id, exDate: flag.ex_date, ...decision }),
      })
      .execute();
    return true;
  });
}
