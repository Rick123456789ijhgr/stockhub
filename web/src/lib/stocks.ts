import "server-only";

import { type Kysely, sql } from "kysely";

import type { ChartBar } from "@/lib/chart-data";
import type { DB } from "@/lib/db";

export type Market = "twse" | "tpex";

export const MARKET_LABEL: Record<Market, string> = { twse: "上市", tpex: "上櫃" };

export type StockListItem = {
  symbol: string;
  name: string;
  market: Market;
  type: "stock" | "etf";
  industry: string | null;
  delistedDate: string | null;
  tradeDate: string | null;
  close: string | null;
  /** Previous close on the latest bar's share basis (see `rebasedPrevClose`). */
  prevClose: string | null;
  volume: string | null;
};

/**
 * Stocks matching `query` (symbol prefix or name substring), each with its latest bar and
 * the previous close rebased with adj_factor, so the change on an ex-date is measured
 * against the reference price instead of the pre-dividend close. Delisted stocks only
 * appear when searched for, after the active ones.
 */
export async function searchStocks(
  db: Kysely<DB>,
  query: string,
  limit = 100,
): Promise<StockListItem[]> {
  const q = query.trim();
  const filter = q
    ? sql`AND (s.symbol ILIKE ${`${q}%`} OR s.name ILIKE ${`%${q}%`})`
    : sql``;
  const result = await sql<StockListItem>`
    SELECT s.symbol, s.name, s.market, s.type, s.industry, s.delisted_date AS "delistedDate",
           l.trade_date AS "tradeDate", l.close, l.prev_close AS "prevClose", l.volume
    FROM stocks s
    LEFT JOIN LATERAL (
      SELECT p.trade_date, p.close, p.volume::text AS volume,
             (SELECT round(p2.close * p2.adj_factor / p.adj_factor, 4) FROM prices_daily p2
               WHERE p2.stock_id = s.id AND p2.trade_date < p.trade_date AND p2.close IS NOT NULL
               ORDER BY p2.trade_date DESC LIMIT 1) AS prev_close
      FROM prices_daily p
      WHERE p.stock_id = s.id
      ORDER BY p.trade_date DESC
      LIMIT 1
    ) l ON true
    WHERE (s.delisted_date IS NULL OR ${q} <> '') ${filter}
    ORDER BY (s.symbol = ${q}) DESC, (s.delisted_date IS NULL) DESC, s.type DESC, s.symbol,
             s.delisted_date DESC
    LIMIT ${limit}
  `.execute(db);
  return result.rows;
}

export type StockDetail = {
  id: number;
  symbol: string;
  name: string;
  market: Market;
  type: "stock" | "etf";
  industry: string | null;
  listedDate: string;
  listedDateEstimated: boolean;
  delistedDate: string | null;
};

/** The listing for `symbol`: the active one, else the most recently delisted. */
export async function findStock(db: Kysely<DB>, symbol: string): Promise<StockDetail | null> {
  const stock = await db
    .selectFrom("stocks")
    .select([
      "id",
      "symbol",
      "name",
      "market",
      "type",
      "industry",
      "listed_date as listedDate",
      "listed_date_estimated as listedDateEstimated",
      "delisted_date as delistedDate",
    ])
    .where("symbol", "=", symbol)
    .orderBy(sql`delisted_date IS NULL`, "desc")
    .orderBy("delisted_date", "desc")
    .executeTakeFirst();
  if (!stock) return null;
  return {
    ...stock,
    id: Number(stock.id),
    market: stock.market as Market,
    type: stock.type as StockDetail["type"],
  };
}

export type DailyBarRow = {
  tradeDate: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  /** Previous close on this bar's share basis (see `rebasedPrevClose`). */
  prevClose: string | null;
  volume: string;
  turnover: string;
  adjFactor: string;
};

/**
 * `prevClose` restated on the basis of a bar with `adjFactor`: on an ex-dividend day this
 * is the reference price, so the change shows the real move (exchange convention).
 */
export function rebasedPrevClose(
  prevClose: string,
  prevFactor: string,
  adjFactor: string,
): string {
  return ((Number(prevClose) * Number(prevFactor)) / Number(adjFactor)).toFixed(4);
}

/** The latest `days` bars of a stock, newest first. */
export async function getRecentBars(
  db: Kysely<DB>,
  stockId: number,
  days = 120,
): Promise<DailyBarRow[]> {
  // One extra row so the oldest shown bar still has a previous close.
  const rows = await db
    .selectFrom("prices_daily")
    .select([
      "trade_date as tradeDate",
      "open",
      "high",
      "low",
      "close",
      sql<string>`volume::text`.as("volume"),
      "turnover",
      "adj_factor as adjFactor",
    ])
    .where("stock_id", "=", String(stockId))
    .orderBy("trade_date", "desc")
    .limit(days + 1)
    .execute();

  return rows.slice(0, days).map((row, i) => {
    const prev = rows.slice(i + 1).find((r) => r.close !== null);
    return {
      ...row,
      prevClose: prev?.close ? rebasedPrevClose(prev.close, prev.adjFactor, row.adjFactor) : null,
    };
  });
}

/** Every traded bar of a stock, oldest first, as compact numbers for the chart. */
export async function getChartBars(db: Kysely<DB>, stockId: number): Promise<ChartBar[]> {
  const result = await sql<{ t: string; o: string; h: string; l: string; c: string; v: string; f: string }>`
    SELECT trade_date AS t, open AS o, high AS h, low AS l, close AS c, volume AS v, adj_factor AS f
    FROM prices_daily
    WHERE stock_id = ${stockId} AND close IS NOT NULL
    ORDER BY trade_date
  `.execute(db);
  return result.rows.map((r) => [
    r.t,
    Number(r.o),
    Number(r.h),
    Number(r.l),
    Number(r.c),
    Number(r.v),
    Number(r.f),
  ]);
}
