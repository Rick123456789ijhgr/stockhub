import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import {
  adjustedChange,
  HEATMAP_PERIODS,
  type HeatmapGroup,
  type HeatmapPeriod,
  type HeatmapStock,
  industryGroups,
  themeGroups,
} from "@/lib/heatmap-data";

export type HeatmapData = {
  /** Latest trading date with closes, and the date the period is measured from. */
  date: string;
  baseDate: string | null;
  groups: HeatmapGroup[];
};

/**
 * Trading dates with TWSE closes, newest first (prices_daily_coverage, not prices_daily).
 * A date counts once most of the market is in, so a half-loaded day is not "latest".
 */
async function recentTradingDates(db: Kysely<DB>, count: number): Promise<string[]> {
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

/** Common stocks with a close on the latest date and their change over the period. */
async function loadStocks(db: Kysely<DB>, date: string, baseDate: string | null) {
  const rows = await sql<{
    id: string;
    symbol: string;
    name: string;
    industry: string | null;
    issued_shares: string;
    close: string;
    adj_factor: string;
    base_close: string | null;
    base_factor: string | null;
  }>`
    SELECT s.id, s.symbol, s.name, s.industry, s.issued_shares, p.close, p.adj_factor,
           b.close AS base_close, b.adj_factor AS base_factor
    FROM stocks s
    JOIN prices_daily p ON p.stock_id = s.id AND p.trade_date = ${date}
    LEFT JOIN LATERAL (
      SELECT close, adj_factor FROM prices_daily
      WHERE stock_id = s.id AND trade_date <= ${baseDate} AND close IS NOT NULL
      ORDER BY trade_date DESC LIMIT 1
    ) b ON ${baseDate}::date IS NOT NULL
    WHERE s.type = 'stock' AND s.delisted_date IS NULL AND p.close IS NOT NULL
      AND s.issued_shares > 0
  `.execute(db);
  return rows.rows.map((r): HeatmapStock => ({
    id: Number(r.id),
    symbol: r.symbol,
    name: r.name,
    industry: r.industry,
    marketCap: Number(r.close) * Number(r.issued_shares),
    change: adjustedChange(
      Number(r.close),
      Number(r.adj_factor),
      r.base_close === null ? null : Number(r.base_close),
      r.base_factor === null ? null : Number(r.base_factor),
    ),
  }));
}

export async function loadHeatmap(
  db: Kysely<DB>,
  by: "industry" | "theme",
  period: HeatmapPeriod,
): Promise<HeatmapData | null> {
  const days = HEATMAP_PERIODS[period];
  const dates = await recentTradingDates(db, days + 1);
  if (!dates.length) return null;
  const date = dates[0];
  const baseDate = dates[days] ?? null;
  const stocks = await loadStocks(db, date, baseDate);
  if (by === "industry") return { date, baseDate, groups: industryGroups(stocks) };
  const members = await db
    .selectFrom("stock_themes as st")
    .innerJoin("themes as t", "t.id", "st.theme_id")
    .select(["st.theme_id", "t.name", "st.stock_id"])
    .where("st.valid_from", "<=", date)
    .where((eb) => eb.or([eb("st.valid_to", "is", null), eb("st.valid_to", ">=", date)]))
    .execute();
  const memberships = members.map((m) => ({
    themeId: Number(m.theme_id),
    themeName: m.name,
    stockId: Number(m.stock_id),
  }));
  return { date, baseDate, groups: themeGroups(stocks, memberships) };
}

/** Themes a stock belongs to today (for the stock page). */
export async function stockThemes(
  db: Kysely<DB>,
  stockId: number,
  today: string,
): Promise<{ id: number; name: string }[]> {
  const rows = await db
    .selectFrom("stock_themes as st")
    .innerJoin("themes as t", "t.id", "st.theme_id")
    .select(["t.id", "t.name"])
    .where("st.stock_id", "=", String(stockId))
    .where("st.valid_from", "<=", today)
    .where((eb) => eb.or([eb("st.valid_to", "is", null), eb("st.valid_to", ">=", today)]))
    .orderBy("t.name")
    .execute();
  return rows.map((t) => ({ id: Number(t.id), name: t.name }));
}
