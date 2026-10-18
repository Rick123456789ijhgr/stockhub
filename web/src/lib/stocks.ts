import "server-only";

import { type Kysely, sql } from "kysely";

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
  prevClose: string | null;
  volume: string | null;
};

/**
 * Stocks matching `query` (symbol prefix or name substring), each with its latest
 * bar and the previous close. Change is raw close-to-close: not yet adjusted for
 * dividends (adj_factor arrives with corporate actions). Delisted stocks only appear when
 * searched for, after the active ones.
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
             (SELECT p2.close FROM prices_daily p2
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
  symbol: string;
  name: string;
  market: Market;
  type: "stock" | "etf";
  industry: string | null;
  listedDate: string;
  listedDateEstimated: boolean;
  delistedDate: string | null;
};

export type DailyBarRow = {
  tradeDate: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  prevClose: string | null;
  volume: string;
  turnover: string;
};

/**
 * The listing for `symbol` (the active one, else the most recently delisted) and its
 * latest `days` bars, newest first.
 */
export async function getStockWithBars(
  db: Kysely<DB>,
  symbol: string,
  days = 120,
): Promise<{ stock: StockDetail; bars: DailyBarRow[] } | null> {
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
    ])
    .where("stock_id", "=", stock.id)
    .orderBy("trade_date", "desc")
    .limit(days + 1)
    .execute();

  const bars = rows.slice(0, days).map((row, i) => ({
    ...row,
    prevClose: rows.slice(i + 1).find((r) => r.close !== null)?.close ?? null,
  }));
  const detail: StockDetail = {
    symbol: stock.symbol,
    name: stock.name,
    market: stock.market as Market,
    type: stock.type as StockDetail["type"],
    industry: stock.industry,
    listedDate: stock.listedDate,
    listedDateEstimated: stock.listedDateEstimated,
    delistedDate: stock.delistedDate,
  };
  return { stock: detail, bars };
}
