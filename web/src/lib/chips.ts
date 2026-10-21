import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";

const num = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));

/** Latest chip metrics of one stock (compute_chip_summary, engine/chips.py). */
export type ChipSummary = {
  tradeDate: string;
  foreignStreak: number;
  trustStreak: number;
  dealerStreak: number;
  foreignNet5d: number;
  foreignNet20d: number;
  trustNet5d: number;
  trustNet20d: number;
  dealerNet5d: number;
  dealerNet20d: number;
  totalNet5d: number;
  totalNet20d: number;
  totalVolumeRatio5d: number | null;
  marginUtilization: number | null;
  shortMarginRatio: number | null;
  marginChange5d: number | null;
  shortChange5d: number | null;
  foreignRatio: number | null;
  foreignRatioChange20d: number | null;
  bigHolderWeek: string | null;
  bigHolderRatio: number | null;
  bigHolderChange1w: number | null;
  whaleRatio: number | null;
  whaleChange1w: number | null;
};

export async function getChipSummary(db: Kysely<DB>, stockId: number): Promise<ChipSummary | null> {
  const r = await db
    .selectFrom("chip_summary")
    .selectAll()
    .where("stock_id", "=", String(stockId))
    .executeTakeFirst();
  if (!r) return null;
  return {
    tradeDate: String(r.trade_date),
    foreignStreak: r.foreign_streak,
    trustStreak: r.trust_streak,
    dealerStreak: r.dealer_streak,
    foreignNet5d: Number(r.foreign_net_5d),
    foreignNet20d: Number(r.foreign_net_20d),
    trustNet5d: Number(r.trust_net_5d),
    trustNet20d: Number(r.trust_net_20d),
    dealerNet5d: Number(r.dealer_net_5d),
    dealerNet20d: Number(r.dealer_net_20d),
    totalNet5d: Number(r.total_net_5d),
    totalNet20d: Number(r.total_net_20d),
    totalVolumeRatio5d: num(r.total_volume_ratio_5d),
    marginUtilization: num(r.margin_utilization),
    shortMarginRatio: num(r.short_margin_ratio),
    marginChange5d: num(r.margin_change_5d),
    shortChange5d: num(r.short_change_5d),
    foreignRatio: num(r.foreign_ratio),
    foreignRatioChange20d: num(r.foreign_ratio_change_20d),
    bigHolderWeek: r.big_holder_week === null ? null : String(r.big_holder_week),
    bigHolderRatio: num(r.big_holder_ratio),
    bigHolderChange1w: num(r.big_holder_change_1w),
    whaleRatio: num(r.whale_ratio),
    whaleChange1w: num(r.whale_change_1w),
  };
}

/** One trading day of a stock's chips; null = that table has no row (or no data yet). */
export type ChipDay = {
  date: string;
  foreignNet: number | null;
  trustNet: number | null;
  dealerNet: number | null;
  totalNet: number | null;
  marginBalance: number | null;
  shortBalance: number | null;
  foreignRatio: number | null;
};

/**
 * The stock's chips on its latest `days` trading days with any chip row, oldest first.
 * Institutional tables only list stocks that institutions traded, so a day with margin data
 * but no institutional row means no institutional trade (0) once that market publishes the
 * table (`institutionalSince`).
 */
export async function getChipDays(
  db: Kysely<DB>,
  stockId: number,
  market: string,
  days = 120,
): Promise<{ rows: ChipDay[]; institutionalSince: string | null }> {
  const [rows, since] = await Promise.all([
    sql<{
      date: string;
      foreign_net: string | null;
      trust_net: string | null;
      dealer_net: string | null;
      total_net: string | null;
      margin_balance: string | null;
      short_balance: string | null;
      foreign_ratio: string | null;
    }>`
      WITH d AS (
        SELECT trade_date FROM (
          SELECT trade_date FROM institutional_trades_daily WHERE stock_id = ${stockId}
          UNION SELECT trade_date FROM margin_daily WHERE stock_id = ${stockId}
          UNION SELECT trade_date FROM foreign_holdings_daily WHERE stock_id = ${stockId}
        ) u ORDER BY trade_date DESC LIMIT ${days})
      SELECT d.trade_date AS date, i.foreign_net, i.trust_net, i.dealer_net, i.total_net,
        m.margin_balance, m.short_balance, f.foreign_ratio
      FROM d
      LEFT JOIN institutional_trades_daily i ON i.stock_id = ${stockId} AND i.trade_date = d.trade_date
      LEFT JOIN margin_daily m ON m.stock_id = ${stockId} AND m.trade_date = d.trade_date
      LEFT JOIN foreign_holdings_daily f ON f.stock_id = ${stockId} AND f.trade_date = d.trade_date
      ORDER BY d.trade_date
    `.execute(db),
    db
      .selectFrom("chip_coverage")
      .select(sql<string | null>`min(trade_date)::text`.as("since"))
      .where("dataset", "=", "institutional")
      .where("market", "=", market)
      .where("rows", ">", 0)
      .executeTakeFirst(),
  ]);
  const institutionalSince = since?.since ?? null;
  return {
    institutionalSince,
    rows: rows.rows.map((r) => {
      const published = institutionalSince !== null && r.date >= institutionalSince;
      const flow = (v: string | null) => (v !== null ? Number(v) : published ? 0 : null);
      return {
        date: r.date,
        foreignNet: flow(r.foreign_net),
        trustNet: flow(r.trust_net),
        dealerNet: flow(r.dealer_net),
        totalNet: flow(r.total_net),
        marginBalance: num(r.margin_balance),
        shortBalance: num(r.short_balance),
        foreignRatio: num(r.foreign_ratio),
      };
    }),
  };
}

export type HolderWeek = {
  week: string;
  bigHolderRatio: number | null;
  whaleRatio: number | null;
  holders: number | null;
};

/** TDCC weeks (shareholding_concentration), oldest first. */
export async function getHolderWeeks(db: Kysely<DB>, stockId: number, weeks = 104): Promise<HolderWeek[]> {
  const rows = await db
    .selectFrom("shareholding_concentration")
    .select(["week_date", "big_holder_ratio", "whale_ratio", "holders"])
    .where("stock_id", "=", String(stockId))
    .orderBy("week_date", "desc")
    .limit(weeks)
    .execute();
  return rows.reverse().map((r) => ({
    week: String(r.week_date),
    bigHolderRatio: num(r.big_holder_ratio),
    whaleRatio: num(r.whale_ratio),
    holders: num(r.holders),
  }));
}

// ----------------------------------------------------------------------------- market

export type MarketFlow = {
  market: "twse" | "tpex";
  tradeDate: string;
  foreign: number | null;
  trust: number | null;
  dealer: number | null;
  total: number | null;
};

/** Net traded value (TWD) per group on each market's latest day with totals. */
export async function getMarketFlows(db: Kysely<DB>): Promise<MarketFlow[]> {
  const rows = await sql<{ market: "twse" | "tpex"; trade_date: string; investor: string; net_amount: string }>`
    SELECT m.market, m.trade_date, m.investor, m.net_amount
    FROM market_institutional_daily m
    JOIN (SELECT market, max(trade_date) AS d FROM market_institutional_daily GROUP BY market) l
      ON l.market = m.market AND l.d = m.trade_date
    ORDER BY m.market DESC
  `.execute(db);
  const out = new Map<string, MarketFlow>();
  for (const r of rows.rows) {
    const flow = out.get(r.market) ?? {
      market: r.market,
      tradeDate: r.trade_date,
      foreign: null,
      trust: null,
      dealer: null,
      total: null,
    };
    if (r.investor === "foreign" || r.investor === "trust" || r.investor === "dealer" || r.investor === "total") {
      flow[r.investor] = Number(r.net_amount);
    }
    out.set(r.market, flow);
  }
  return [...out.values()];
}

export type RankedFlow = {
  symbol: string;
  name: string;
  market: string;
  netShares: number;
  /** Net shares × close: an estimate (the exchanges publish only shares per stock). */
  netValue: number;
  close: number;
};

export type RankingGroup = "total" | "foreign" | "trust" | "dealer";

const NET_COLUMN: Record<RankingGroup, string> = {
  total: "total_net",
  foreign: "foreign_net",
  trust: "trust_net",
  dealer: "dealer_net",
};

/** Biggest net buys and sells of one group on the latest institutional day, by estimated value. */
export async function getFlowRanking(
  db: Kysely<DB>,
  group: RankingGroup,
  limit = 10,
): Promise<{ tradeDate: string | null; buys: RankedFlow[]; sells: RankedFlow[] }> {
  const latest = await db
    .selectFrom("chip_coverage")
    .select(sql<string | null>`max(trade_date)::text`.as("d"))
    .where("dataset", "=", "institutional")
    .where("rows", ">", 0)
    .executeTakeFirst();
  const tradeDate = latest?.d ?? null;
  if (!tradeDate) return { tradeDate, buys: [], sells: [] };
  const column = sql.ref(`i.${NET_COLUMN[group]}`);
  const query = (direction: "asc" | "desc") => sql<{
    symbol: string;
    name: string;
    market: string;
    net: string;
    close: string;
  }>`
    SELECT s.symbol, s.name, s.market, ${column} AS net, p.close
    FROM institutional_trades_daily i
    JOIN stocks s ON s.id = i.stock_id
    JOIN prices_daily p ON p.stock_id = i.stock_id AND p.trade_date = i.trade_date
    WHERE i.trade_date = ${tradeDate} AND p.close IS NOT NULL
      AND ${column} ${direction === "desc" ? sql`> 0` : sql`< 0`}
    ORDER BY ${column} * p.close ${direction === "desc" ? sql`DESC` : sql`ASC`}
    LIMIT ${limit}
  `.execute(db);
  const [buys, sells] = await Promise.all([query("desc"), query("asc")]);
  const map = (r: { symbol: string; name: string; market: string; net: string; close: string }) => ({
    symbol: r.symbol,
    name: r.name,
    market: r.market,
    netShares: Number(r.net),
    close: Number(r.close),
    netValue: Number(r.net) * Number(r.close),
  });
  return { tradeDate, buys: buys.rows.map(map), sells: sells.rows.map(map) };
}

// ----------------------------------------------------------------------------- status

export type ChipCoverageRow = {
  dataset: string;
  market: string;
  first: string | null;
  last: string | null;
  days: number;
};

export type ChipsStatus = {
  coverage: ChipCoverageRow[];
  summaries: number;
  quarantinePending: number;
  backfill: { id: string; startedAt: string; done: number; total: number; next: string | null } | null;
};

export async function getChipsStatus(db: Kysely<DB>): Promise<ChipsStatus> {
  const [coverage, counts, run] = await Promise.all([
    sql<ChipCoverageRow>`
      SELECT dataset, market, min(trade_date)::text AS first, max(trade_date)::text AS last,
        count(*)::int AS days
      FROM chip_coverage WHERE rows > 0 GROUP BY dataset, market ORDER BY dataset, market DESC
    `.execute(db),
    sql<{ summaries: number; quarantine: number }>`
      SELECT (SELECT count(*) FROM chip_summary)::int AS summaries,
        (SELECT count(*) FROM chip_quarantine WHERE resolved_at IS NULL)::int AS quarantine
    `.execute(db),
    db
      .selectFrom("job_runs")
      .select(["id", "started_at", "checkpoint"])
      .where("job_name", "=", "backfill_chips")
      .where("status", "=", "running")
      .orderBy("started_at", "desc")
      .limit(1)
      .executeTakeFirst(),
  ]);
  const checkpoint = (run?.checkpoint ?? {}) as { done?: number; total?: number; next?: string };
  return {
    coverage: coverage.rows,
    summaries: counts.rows[0]?.summaries ?? 0,
    quarantinePending: counts.rows[0]?.quarantine ?? 0,
    backfill: run
      ? {
          id: String(run.id),
          startedAt: run.started_at.toISOString(),
          done: checkpoint.done ?? 0,
          total: checkpoint.total ?? 0,
          next: checkpoint.next ?? null,
        }
      : null,
  };
}
