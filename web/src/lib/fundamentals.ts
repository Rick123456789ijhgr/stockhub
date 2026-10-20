import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { Dividend, PricePoint, QuarterPoint } from "@/lib/valuation";

/** Industries whose statements follow the financial templates (M3b). */
export const FINANCIAL_INDUSTRIES = new Set(["金融保險業"]);

const num = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));

export type QuarterRow = {
  periodEnd: string;
  availableDate: string;
  revenue: number | null;
  grossProfit: number | null;
  operatingIncome: number | null;
  netIncome: number | null;
  netIncomeParent: number | null;
  eps: number | null;
  epsTtm: number | null;
  operatingCashFlow: number | null;
  capitalExpenditure: number | null;
  freeCashFlow: number | null;
  freeCashFlowTtm: number | null;
  bvps: number | null;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
  roeTtm: number | null;
  roaTtm: number | null;
  dupontNetMargin: number | null;
  dupontAssetTurnover: number | null;
  dupontEquityMultiplier: number | null;
  debtRatio: number | null;
  currentRatio: number | null;
  revenueYoy: number | null;
  epsYoy: number | null;
  sources: Record<string, string>;
};

/** Every derived quarter of a company, oldest first. */
export async function getQuarters(db: Kysely<DB>, stockId: number): Promise<QuarterRow[]> {
  const rows = await db
    .selectFrom("fundamentals_quarterly")
    .selectAll()
    .where("stock_id", "=", String(stockId))
    .orderBy("period_end")
    .execute();
  return rows.map((r) => ({
    periodEnd: String(r.period_end),
    availableDate: String(r.available_date),
    revenue: num(r.revenue),
    grossProfit: num(r.gross_profit),
    operatingIncome: num(r.operating_income),
    netIncome: num(r.net_income),
    netIncomeParent: num(r.net_income_parent),
    eps: num(r.eps),
    epsTtm: num(r.eps_ttm),
    operatingCashFlow: num(r.operating_cash_flow),
    capitalExpenditure: num(r.capital_expenditure),
    freeCashFlow: num(r.free_cash_flow),
    freeCashFlowTtm: num(r.free_cash_flow_ttm),
    bvps: num(r.bvps),
    grossMargin: num(r.gross_margin),
    operatingMargin: num(r.operating_margin),
    netMargin: num(r.net_margin),
    roeTtm: num(r.roe_ttm),
    roaTtm: num(r.roa_ttm),
    dupontNetMargin: num(r.dupont_net_margin),
    dupontAssetTurnover: num(r.dupont_asset_turnover),
    dupontEquityMultiplier: num(r.dupont_equity_multiplier),
    debtRatio: num(r.debt_ratio),
    currentRatio: num(r.current_ratio),
    revenueYoy: num(r.revenue_yoy),
    epsYoy: num(r.eps_yoy),
    sources: (r.sources ?? {}) as Record<string, string>,
  }));
}

export type RevenueRow = {
  month: string;
  revenue: number;
  mom: number | null;
  yoy: number | null;
  ytdYoy: number | null;
};

/** Monthly revenue with growth (view monthly_revenue_growth), oldest first. */
export async function getMonthlyRevenue(
  db: Kysely<DB>,
  stockId: number,
  months = 72,
): Promise<RevenueRow[]> {
  const result = await sql<{
    month: string;
    revenue: string;
    mom: string | null;
    yoy: string | null;
    ytd_yoy: string | null;
  }>`
    SELECT revenue_month::text AS month, revenue, mom, yoy, ytd_yoy
    FROM monthly_revenue_growth WHERE stock_id = ${stockId}
    ORDER BY revenue_month DESC LIMIT ${months}
  `.execute(db);
  return result.rows.reverse().map((r) => ({
    month: r.month,
    revenue: Number(r.revenue),
    mom: num(r.mom),
    yoy: num(r.yoy),
    ytdYoy: num(r.ytd_yoy),
  }));
}

export type SignalRow = {
  code: string;
  periodEnd: string;
  direction: "up" | "down" | "neutral";
  title: string;
};

export async function getSignals(db: Kysely<DB>, stockId: number, limit = 12): Promise<SignalRow[]> {
  const rows = await db
    .selectFrom("fundamental_signals")
    .select(["code", "period_end", "direction", "title"])
    .where("stock_id", "=", String(stockId))
    .orderBy("period_end", "desc")
    .orderBy("code")
    .limit(limit)
    .execute();
  return rows.map((r) => ({
    code: r.code,
    periodEnd: String(r.period_end),
    direction: r.direction as SignalRow["direction"],
    title: r.title,
  }));
}

export type ValuationInputs = {
  prices: PricePoint[];
  quarters: QuarterPoint[];
  dividends: Dividend[];
};

/** Raw closes since `since`, quarters (with availability) and cash dividends. */
export async function getValuationInputs(
  db: Kysely<DB>,
  stockId: number,
  since: string,
): Promise<ValuationInputs> {
  const [prices, quarters, dividends] = await Promise.all([
    sql<{ date: string; close: string }>`
      SELECT trade_date::text AS date, close FROM prices_daily
      WHERE stock_id = ${stockId} AND trade_date >= ${since}::date AND close IS NOT NULL
      ORDER BY trade_date
    `.execute(db),
    sql<{ period_end: string; available_date: string; eps_ttm: string | null; bvps: string | null }>`
      SELECT period_end::text, available_date::text, eps_ttm, bvps FROM fundamentals_quarterly
      WHERE stock_id = ${stockId} ORDER BY period_end
    `.execute(db),
    sql<{ ex_date: string; cash: string }>`
      SELECT ex_date::text, cash_dividend AS cash FROM corporate_actions
      WHERE stock_id = ${stockId} AND cash_dividend > 0
        AND action_type IN ('cash_dividend', 'cash_and_stock_dividend')
        AND ex_date >= ${since}::date - 366
      ORDER BY ex_date
    `.execute(db),
  ]);
  return {
    prices: prices.rows.map((r) => ({ date: r.date, close: Number(r.close) })),
    quarters: quarters.rows.map((r) => ({
      periodEnd: r.period_end,
      availableDate: r.available_date,
      epsTtm: num(r.eps_ttm),
      bvps: num(r.bvps),
    })),
    dividends: dividends.rows.map((r) => ({ exDate: r.ex_date, cash: Number(r.cash) })),
  };
}

export type QuoteFundamentals = {
  /** Latest quarter available on `today` (same rule as the valuation series). */
  epsTtm: number | null;
  bvps: number | null;
  issuedShares: number | null;
};

/** Per-share figures and share count for the quote header's P/E, P/B and market value. */
export async function getQuoteFundamentals(
  db: Kysely<DB>,
  stockId: number,
  today: string,
): Promise<QuoteFundamentals> {
  const result = await sql<{ eps_ttm: string | null; bvps: string | null; shares: string | null }>`
    SELECT f.eps_ttm, f.bvps, s.issued_shares AS shares
    FROM stocks s
    LEFT JOIN LATERAL (
      SELECT eps_ttm, bvps FROM fundamentals_quarterly
      WHERE stock_id = s.id AND available_date <= ${today}::date
      ORDER BY period_end DESC LIMIT 1) f ON true
    WHERE s.id = ${stockId}
  `.execute(db);
  const row = result.rows[0];
  return {
    epsTtm: num(row?.eps_ttm ?? null),
    bvps: num(row?.bvps ?? null),
    issuedShares: num(row?.shares ?? null),
  };
}

export type PeerRow = {
  stockId: number;
  symbol: string;
  name: string;
  close: number | null;
  marketCap: number | null;
  pe: number | null;
  pb: number | null;
  dividendYield: number | null;
  roeTtm: number | null;
  grossMargin: number | null;
  revenueYoy: number | null;
  revenueMonth: string | null;
};

/**
 * Listed companies of the same industry with the figures available today (same rules as
 * lib/valuation.ts: latest quarter by available date, P/E only on positive TTM EPS, trailing
 * cash yield), largest first by market value.
 */
export async function getPeers(
  db: Kysely<DB>,
  industry: string,
  today: string,
): Promise<PeerRow[]> {
  const result = await sql<{
    id: string;
    symbol: string;
    name: string;
    close: string | null;
    shares: string | null;
    eps_ttm: string | null;
    bvps: string | null;
    roe_ttm: string | null;
    gross_margin: string | null;
    dividend: string | null;
    yoy: string | null;
    month: string | null;
  }>`
    SELECT s.id, s.symbol, s.name, p.close, s.issued_shares AS shares,
           f.eps_ttm, f.bvps, f.roe_ttm, f.gross_margin, d.dividend, r.yoy, r.month
    FROM stocks s
    LEFT JOIN LATERAL (
      SELECT close FROM prices_daily WHERE stock_id = s.id AND close IS NOT NULL
      ORDER BY trade_date DESC LIMIT 1) p ON true
    LEFT JOIN LATERAL (
      SELECT eps_ttm, bvps, roe_ttm, gross_margin FROM fundamentals_quarterly
      WHERE stock_id = s.id AND available_date <= ${today}::date
      ORDER BY period_end DESC LIMIT 1) f ON true
    LEFT JOIN LATERAL (
      SELECT sum(cash_dividend) AS dividend FROM corporate_actions
      WHERE stock_id = s.id AND cash_dividend > 0
        AND action_type IN ('cash_dividend', 'cash_and_stock_dividend')
        AND ex_date > ${today}::date - 365 AND ex_date <= ${today}::date) d ON true
    LEFT JOIN LATERAL (
      SELECT yoy, revenue_month::text AS month FROM monthly_revenue_growth
      WHERE stock_id = s.id ORDER BY revenue_month DESC LIMIT 1) r ON true
    WHERE s.industry = ${industry} AND s.delisted_date IS NULL AND s.type = 'stock'
  `.execute(db);
  const rows = result.rows.map((r) => {
    const close = num(r.close);
    const eps = num(r.eps_ttm);
    const bvps = num(r.bvps);
    const shares = num(r.shares);
    return {
      stockId: Number(r.id),
      symbol: r.symbol,
      name: r.name,
      close,
      marketCap: close !== null && shares !== null ? close * shares : null,
      pe: close !== null && close > 0 && eps !== null && eps > 0 ? close / eps : null,
      pb: close !== null && close > 0 && bvps !== null && bvps > 0 ? close / bvps : null,
      dividendYield: close !== null && close > 0 ? (num(r.dividend) ?? 0) / close : null,
      roeTtm: num(r.roe_ttm),
      grossMargin: num(r.gross_margin),
      revenueYoy: num(r.yoy),
      revenueMonth: r.month,
    };
  });
  rows.sort((a, b) => (b.marketCap ?? -1) - (a.marketCap ?? -1));
  return rows;
}
