import "server-only";

import { type Kysely, sql } from "kysely";

import type { ChartBar } from "@/lib/chart-data";
import type { DB } from "@/lib/db";

import type { Market } from "@/lib/stock-market";
import { escapeLike, normalizeQuery } from "@/lib/stock-search";

export { MARKET_LABEL, type Market } from "@/lib/stock-market";

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
  /** TWD. */
  turnover: string | null;
  /** Close × issued shares (TWD); null for ETFs and when shares are unknown. */
  marketCap: string | null;
};

/**
 * Listings whose symbol or name contains `query` (878 finds 00878), best match first:
 * exact symbol, symbol prefix, name prefix, then anything containing it; within each, the
 * listed ones before delisted, the most traded first. Symbols also match without their
 * leading zeros, so 50 is an exact match for 0050 and 878 a prefix of 00878. Each comes with its latest bar and
 * the previous close rebased with adj_factor, so the change on an ex-date is measured
 * against the reference price instead of the pre-dividend close.
 */
export async function searchStocks(
  db: Kysely<DB>,
  query: string,
  limit = 100,
): Promise<StockListItem[]> {
  const q = normalizeQuery(query);
  if (!q) return [];
  const like = escapeLike(q);
  const result = await sql<StockListItem>`
    SELECT s.symbol, s.name, s.market, s.type, s.industry, s.delisted_date AS "delistedDate",
           l.trade_date AS "tradeDate", l.close, l.prev_close AS "prevClose", l.volume,
           l.turnover, ${MARKET_CAP_SQL} AS "marketCap"
    FROM stocks s
    LEFT JOIN LATERAL (
      SELECT p.trade_date, p.close, p.volume::text AS volume, p.turnover,
             (SELECT round(p2.close * p2.adj_factor / p.adj_factor, 4) FROM prices_daily p2
               WHERE p2.stock_id = s.id AND p2.trade_date < p.trade_date AND p2.close IS NOT NULL
               ORDER BY p2.trade_date DESC LIMIT 1) AS prev_close
      FROM prices_daily p
      WHERE p.stock_id = s.id
      ORDER BY p.trade_date DESC
      LIMIT 1
    ) l ON true
    WHERE s.symbol ILIKE ${`%${like}%`} OR s.name ILIKE ${`%${like}%`}
    ORDER BY (upper(s.symbol) = upper(${q}) OR ltrim(s.symbol, '0') = ${q}) DESC,
             (s.symbol ILIKE ${`${like}%`} OR ltrim(s.symbol, '0') ILIKE ${`${like}%`}) DESC,
             s.name ILIKE ${`${like}%`} DESC,
             s.delisted_date IS NULL DESC,
             l.turnover DESC NULLS LAST,
             s.symbol, s.delisted_date DESC
    LIMIT ${limit}
  `.execute(db);
  return result.rows;
}

/** close × issued shares of `s` and lateral/row `l`, for common stocks only. */
const MARKET_CAP_SQL = sql`CASE WHEN s.type = 'stock' AND s.issued_shares > 0
  THEN round(l.close * s.issued_shares) END`;

export const RANKINGS = ["turnover", "volume", "gainers", "losers", "marketCap"] as const;
export type Ranking = (typeof RANKINGS)[number];
/** Rankings are of common stocks or of ETFs, never mixed; ETFs have no market value. */
export type RankingKind = "stock" | "etf";

const RANKING_ORDER: Record<Ranking, ReturnType<typeof sql>> = {
  turnover: sql`l.turnover DESC`,
  volume: sql`l.volume::bigint DESC`,
  gainers: sql`l.close / l.prev_close DESC`,
  losers: sql`l.close / l.prev_close ASC`,
  marketCap: sql`${MARKET_CAP_SQL} DESC NULLS LAST`,
};

/**
 * Trading dates with TWSE closes, newest first (prices_daily_coverage, not prices_daily).
 * A date counts once most of the market is in, so a half-loaded day is not "latest".
 */
export async function recentTradingDates(db: Kysely<DB>, count: number): Promise<string[]> {
  const rows = await db
    .selectFrom("prices_daily_coverage")
    .select("trade_date")
    .where("market", "=", "twse")
    .where("bars", ">", 500)
    .orderBy("trade_date", "desc")
    .limit(count)
    .execute();
  return rows.map((r) => String(r.trade_date));
}

/**
 * The top `limit` common stocks or ETFs of the latest trading day by `ranking`. Changes use
 * the previous close rebased with adj_factor, like everywhere else.
 */
export async function getRanking(
  db: Kysely<DB>,
  ranking: Ranking,
  kind: RankingKind,
  limit = 50,
): Promise<{ date: string | null; rows: StockListItem[] }> {
  const [date] = await recentTradingDates(db, 1);
  if (!date) return { date: null, rows: [] };
  const movers =
    ranking === "gainers" || ranking === "losers" ? sql`AND l.prev_close > 0` : sql``;
  const result = await sql<StockListItem>`
    SELECT s.symbol, s.name, s.market, s.type, s.industry, s.delisted_date AS "delistedDate",
           l.trade_date AS "tradeDate", l.close, l.prev_close AS "prevClose", l.volume,
           l.turnover, ${MARKET_CAP_SQL} AS "marketCap"
    FROM (
      SELECT p.stock_id, p.trade_date, p.close, p.volume::text AS volume, p.turnover,
             (SELECT round(p2.close * p2.adj_factor / p.adj_factor, 4) FROM prices_daily p2
               WHERE p2.stock_id = p.stock_id AND p2.trade_date < p.trade_date
                 AND p2.close IS NOT NULL
               ORDER BY p2.trade_date DESC LIMIT 1) AS prev_close
      FROM prices_daily p
      WHERE p.trade_date = ${date} AND p.close IS NOT NULL
    ) l
    JOIN stocks s ON s.id = l.stock_id
    WHERE s.delisted_date IS NULL AND s.type = ${kind} ${movers}
    ORDER BY ${RANKING_ORDER[ranking]}, s.symbol
    LIMIT ${limit}
  `.execute(db);
  return { date, rows: result.rows };
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

/** Months of bars in the chart's first, fast load: 3 years + indicator warm-up. */
export const CHART_RECENT_MONTHS = 42;

/**
 * Traded bars of a stock, oldest first, as compact numbers for the chart. With
 * `recentMonths`, only bars within that many months of the latest one; `complete` tells
 * whether older bars exist that were left out.
 */
export async function getChartBars(
  db: Kysely<DB>,
  stockId: number,
  recentMonths?: number,
): Promise<{ bars: ChartBar[]; complete: boolean }> {
  const since =
    recentMonths === undefined
      ? sql`NULL::date`
      : sql`(SELECT max(trade_date) FROM prices_daily WHERE stock_id = ${stockId})
            - make_interval(months => ${recentMonths})`;
  const result = await sql<{ t: string; o: string; h: string; l: string; c: string; v: string; f: string; older: boolean }>`
    WITH cutoff AS (SELECT ${since} AS since)
    SELECT trade_date AS t, open AS o, high AS h, low AS l, close AS c, volume AS v, adj_factor AS f,
           EXISTS (
             SELECT 1 FROM prices_daily o
             WHERE o.stock_id = ${stockId} AND o.close IS NOT NULL
               AND o.trade_date < (SELECT since FROM cutoff)
           ) AS older
    FROM prices_daily
    WHERE stock_id = ${stockId} AND close IS NOT NULL
      AND trade_date >= coalesce((SELECT since FROM cutoff), '-infinity'::date)
    ORDER BY trade_date
  `.execute(db);
  const bars: ChartBar[] = result.rows.map((r) => [
    r.t,
    Number(r.o),
    Number(r.h),
    Number(r.l),
    Number(r.c),
    Number(r.v),
    Number(r.f),
  ]);
  return { bars, complete: !(result.rows[0]?.older ?? false) };
}
