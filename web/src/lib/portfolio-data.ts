import "server-only";

import { type Kysely, sql, type Transaction } from "kysely";

import type { DB } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import {
  type Action,
  type FeeSettings,
  type Issue,
  type Ledger,
  type Mark,
  replay,
  type Security,
  type Totals,
  totals,
  type Trade,
} from "@/lib/portfolio";
import { getFeeSettings } from "@/lib/settings";
import { findStock, type Market } from "@/lib/stocks";
import { charges, type TransactionInput } from "@/lib/transaction-input";

export type StockRef = {
  id: string;
  symbol: string;
  name: string;
  type: "stock" | "etf";
  market: Market;
  delistedDate: string | null;
};

export type TransactionRow = {
  id: string;
  stockId: string;
  symbol: string;
  name: string;
  tradeDate: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  fee: number;
  feeRebate: number;
  tax: number;
  dayTrade: boolean;
  feeManual: boolean;
  taxManual: boolean;
  note: string | null;
};

export type MarkInfo = Mark & { source: "quote" | "daily"; quoteTime: string | null };

export type PortfolioView = {
  asOf: string;
  fees: FeeSettings;
  stocks: Record<string, StockRef>;
  /** Newest first, for display. */
  transactions: TransactionRow[];
  marks: Record<string, MarkInfo>;
  ledger: Ledger;
  totals: Totals;
};

type Db = Kysely<DB> | Transaction<DB>;

/** Every transaction in id order (the replay order), with its stock. */
async function loadTransactions(db: Db): Promise<TransactionRow[]> {
  const rows = await db
    .selectFrom("portfolio_transactions as t")
    .innerJoin("stocks as s", "s.id", "t.stock_id")
    .select([
      sql<string>`t.id::text`.as("id"),
      sql<string>`t.stock_id::text`.as("stockId"),
      "s.symbol",
      "s.name",
      "t.trade_date as tradeDate",
      "t.side",
      sql<string>`t.quantity::text`.as("quantity"),
      "t.price",
      "t.fee",
      "t.fee_rebate as feeRebate",
      "t.tax",
      "t.day_trade as dayTrade",
      "t.fee_manual as feeManual",
      "t.tax_manual as taxManual",
      "t.note",
    ])
    .orderBy("t.id")
    .execute();
  return rows.map((r) => ({
    ...r,
    side: r.side as TransactionRow["side"],
    quantity: Number(r.quantity),
    price: Number(r.price),
    fee: Number(r.fee),
    feeRebate: Number(r.feeRebate),
    tax: Number(r.tax),
  }));
}

function toTrade(r: TransactionRow): Trade {
  return {
    id: r.id,
    stock: r.stockId,
    date: r.tradeDate,
    side: r.side,
    quantity: r.quantity,
    price: r.price,
    fee: r.fee,
    tax: r.tax,
    rebate: r.feeRebate,
  };
}

const numOrNull = (v: string | null) => (v === null ? null : Number(v));

async function loadActions(db: Db, stockIds: string[]): Promise<Action[]> {
  if (stockIds.length === 0) return [];
  const rows = await db
    .selectFrom("corporate_actions")
    .select([
      sql<string>`stock_id::text`.as("stock"),
      "ex_date as exDate",
      "action_type as actionType",
      "cash_dividend as cashDividend",
      "stock_dividend_ratio as stockDividendRatio",
      "ratio",
      "prev_close as prevClose",
      "reference_price as referencePrice",
    ])
    .where("stock_id", "in", stockIds)
    .orderBy("ex_date")
    .orderBy("id")
    .execute();
  return rows.map((r) => ({
    ...r,
    cashDividend: numOrNull(r.cashDividend),
    stockDividendRatio: numOrNull(r.stockDividendRatio),
    ratio: numOrNull(r.ratio),
    prevClose: numOrNull(r.prevClose),
    referencePrice: numOrNull(r.referencePrice),
  }));
}

async function loadStocks(db: Db, stockIds: string[]): Promise<Record<string, StockRef>> {
  if (stockIds.length === 0) return {};
  const rows = await db
    .selectFrom("stocks")
    .select([
      sql<string>`id::text`.as("id"),
      "symbol",
      "name",
      "type",
      "market",
      "delisted_date as delistedDate",
    ])
    .where("id", "in", stockIds)
    .execute();
  return Object.fromEntries(
    rows.map((r) => [
      r.id,
      { ...r, type: r.type as StockRef["type"], market: r.market as Market },
    ]),
  );
}

/**
 * Latest price per stock: today's intraday quote when it is newer than the last daily
 * bar, else the last close. The previous close is on the mark's share basis (the
 * reference price on an ex-date), as everywhere else on the site.
 */
export async function loadMarks(db: Db, stockIds: string[]): Promise<Record<string, MarkInfo>> {
  if (stockIds.length === 0) return {};
  const result = await sql<{
    id: string;
    barDate: string | null;
    close: string | null;
    prevClose: string | null;
    quoteDate: string | null;
    quotePrice: string | null;
    quotePrev: string | null;
    quoteTime: Date | null;
  }>`
    SELECT s.id::text AS id, b.trade_date AS "barDate", b.close, b.prev_close AS "prevClose",
           q.trade_date AS "quoteDate", q.price AS "quotePrice", q.prev_close AS "quotePrev",
           q.quote_time AS "quoteTime"
    FROM stocks s
    LEFT JOIN LATERAL (
      SELECT p.trade_date, p.close,
             (SELECT round(p2.close * p2.adj_factor / p.adj_factor, 4) FROM prices_daily p2
               WHERE p2.stock_id = s.id AND p2.trade_date < p.trade_date AND p2.close IS NOT NULL
               ORDER BY p2.trade_date DESC LIMIT 1) AS prev_close
      FROM prices_daily p
      WHERE p.stock_id = s.id AND p.close IS NOT NULL
      ORDER BY p.trade_date DESC
      LIMIT 1
    ) b ON true
    LEFT JOIN quotes_latest q ON q.stock_id = s.id AND q.price IS NOT NULL
    WHERE s.id = ANY(${stockIds}::bigint[])
  `.execute(db);
  const marks: Record<string, MarkInfo> = {};
  for (const r of result.rows) {
    if (r.quoteDate && r.quotePrice && (r.barDate === null || r.quoteDate > r.barDate)) {
      marks[r.id] = {
        date: r.quoteDate,
        price: Number(r.quotePrice),
        prevClose: numOrNull(r.quotePrev),
        source: "quote",
        quoteTime: r.quoteTime?.toISOString() ?? null,
      };
    } else if (r.barDate && r.close) {
      marks[r.id] = {
        date: r.barDate,
        price: Number(r.close),
        prevClose: numOrNull(r.prevClose),
        source: "daily",
        quoteTime: null,
      };
    }
  }
  return marks;
}

function securities(stocks: Record<string, StockRef>): Record<string, Security> {
  return Object.fromEntries(
    Object.values(stocks).map((s) => [s.id, { type: s.type, symbol: s.symbol }]),
  );
}

/** Everything /portfolio shows, computed by the shared portfolio engine. */
export async function loadPortfolio(db: Kysely<DB>): Promise<PortfolioView> {
  const asOf = taipeiToday();
  const transactions = await loadTransactions(db);
  const stockIds = [...new Set(transactions.map((t) => t.stockId))];
  const [actions, stocks, marks, fees] = await Promise.all([
    loadActions(db, stockIds),
    loadStocks(db, stockIds),
    loadMarks(db, stockIds),
    getFeeSettings(db),
  ]);
  const ledger = replay(transactions.map(toTrade), actions, {
    asOf,
    marks,
    securities: securities(stocks),
    fees,
  });
  return {
    asOf,
    fees,
    stocks,
    transactions: [...transactions].reverse(),
    marks,
    ledger,
    totals: totals(ledger.positions),
  };
}

// --- writes ---------------------------------------------------------------------------

export type TransactionChange =
  | { kind: "create"; input: TransactionInput }
  | { kind: "update"; id: string; input: TransactionInput }
  | { kind: "delete"; id: string };

export type ChangeResult =
  | { ok: true; id: string }
  | { ok: false; status: 400 | 404 | 409; error: string };

const NEW_ID = "new";

function describeIssue(issue: Issue, symbol: string): string {
  return `${issue.date} 賣出 ${symbol} ${issue.quantity.toLocaleString("en-US")} 股，超過當時持股 ${issue.held.toLocaleString("en-US")} 股`;
}

/**
 * Create, update or delete one transaction. Rejected when it would make any sell exceed
 * the holding at that point (checked by replaying the stock's whole ledger, corporate
 * actions included). Fee and tax are recomputed unless entered by hand. Audited.
 */
export async function applyTransactionChange(
  db: Kysely<DB>,
  change: TransactionChange,
  actor: string,
): Promise<ChangeResult> {
  return db.transaction().execute(async (trx) => {
    // One writer at a time, so the oversell check sees the ledger it is applied to.
    await sql`LOCK TABLE portfolio_transactions IN SHARE ROW EXCLUSIVE MODE`.execute(trx);
    const current = await loadTransactions(trx);
    const before = change.kind === "create" ? null : current.find((t) => t.id === change.id);
    if (before === undefined) return { ok: false, status: 404, error: "找不到這筆交易" };

    let after: TransactionRow | null = null;
    if (change.kind !== "delete") {
      const { input } = change;
      const stock = await findStock(trx, input.symbol);
      if (!stock) return { ok: false, status: 400, error: `找不到代號 ${input.symbol}` };
      if (stock.delistedDate && input.tradeDate >= stock.delistedDate) {
        return { ok: false, status: 400, error: `${input.symbol} 已於 ${stock.delistedDate} 終止上市（櫃）` };
      }
      const day = await trx
        .selectFrom("trading_calendar")
        .select("is_trading_day")
        .where("date", "=", input.tradeDate)
        .executeTakeFirst();
      if (day && !day.is_trading_day) {
        return { ok: false, status: 400, error: `${input.tradeDate} 休市` };
      }
      const c = charges(input, { type: stock.type, symbol: stock.symbol }, await getFeeSettings(trx));
      after = {
        id: before?.id ?? NEW_ID,
        stockId: String(stock.id),
        symbol: stock.symbol,
        name: stock.name,
        tradeDate: input.tradeDate,
        side: input.side,
        quantity: input.quantity,
        price: input.price,
        fee: c.fee,
        feeRebate: c.feeRebate,
        tax: c.tax,
        dayTrade: input.dayTrade,
        feeManual: input.fee !== null,
        taxManual: input.side === "sell" && input.tax !== null,
        note: input.note,
      };
    }

    const next = current.filter((t) => t.id !== before?.id);
    if (after) {
      if (before) next.splice(current.indexOf(before), 0, after);
      else next.push(after);
    }
    const touched = [...new Set([before?.stockId, after?.stockId].filter((s) => s !== undefined))];
    const actions = await loadActions(trx, touched);
    const issues = (rows: TransactionRow[]) =>
      replay(rows.filter((t) => touched.includes(t.stockId)).map(toTrade), actions, {
        asOf: taipeiToday(),
      }).issues;
    const known = new Set(issues(current).map((i) => i.id));
    const fresh = issues(next).filter((i) => !known.has(i.id));
    if (fresh.length > 0) {
      const symbol = (id: string) => next.find((t) => t.stockId === id)?.symbol ?? "";
      return { ok: false, status: 409, error: describeIssue(fresh[0], symbol(fresh[0].stock)) };
    }

    let id = before?.id ?? "";
    if (change.kind === "delete") {
      await trx.deleteFrom("portfolio_transactions").where("id", "=", change.id).execute();
    } else if (after) {
      const values = {
        stock_id: after.stockId,
        trade_date: after.tradeDate,
        side: after.side,
        quantity: String(after.quantity),
        price: String(after.price),
        fee: String(after.fee),
        fee_rebate: String(after.feeRebate),
        tax: String(after.tax),
        day_trade: after.dayTrade,
        fee_manual: after.feeManual,
        tax_manual: after.taxManual,
        note: after.note,
      };
      if (before) {
        await trx.updateTable("portfolio_transactions").set(values).where("id", "=", before.id).execute();
      } else {
        const row = await trx
          .insertInto("portfolio_transactions")
          .values(values)
          .returning(sql<string>`id::text`.as("id"))
          .executeTakeFirstOrThrow();
        id = row.id;
        after = { ...after, id };
      }
    }
    await trx
      .insertInto("audit_log")
      .values({
        actor,
        action: `portfolio.${change.kind}`,
        target: (after ?? before)?.symbol ?? null,
        detail: JSON.stringify({ id, before: before ?? null, after }),
      })
      .execute();
    return { ok: true, id };
  });
}
