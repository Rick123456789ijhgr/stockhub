/**
 * Trade form validation and automatic fee / tax (safe for client components). The server
 * re-runs both, so the stored fee and tax never depend on what the browser sent unless
 * they were entered by hand.
 */

import {
  brokerFee,
  type FeeSettings,
  taxRate,
  transactionTax,
} from "@/lib/portfolio";

export type Side = "buy" | "sell";

export const SIDE_LABEL: Record<Side, string> = { buy: "買進", sell: "賣出" };

export type TransactionInput = {
  symbol: string;
  tradeDate: string;
  side: Side;
  quantity: number;
  price: number;
  dayTrade: boolean;
  /** Set when entered by hand; null means "fill in automatically". */
  fee: number | null;
  feeRebate: number | null;
  tax: number | null;
  note: string | null;
};

export type Charges = { fee: number; feeRebate: number; tax: number };

const MAX_QUANTITY = 1_000_000_000;
const MAX_PRICE = 1_000_000;
const MAX_NOTE = 500;

function decimals(value: number): number {
  const text = String(value);
  if (text.includes("e")) return 99;
  return text.split(".")[1]?.length ?? 0;
}

function num(value: unknown): number | null {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}

/** A hand-entered amount: whole TWD cents at most, 0 or more; null/"" means automatic. */
function money(value: unknown): number | null | undefined {
  if (value === null || value === undefined || value === "") return null;
  const n = num(value);
  if (n === null || n < 0 || n > 1e10 || decimals(n) > 2) return undefined;
  return n;
}

export function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

export type ParseResult = { ok: true; value: TransactionInput } | { ok: false; error: string };

/** Validate a POST/PATCH body; `today` (Taipei) bounds the trade date. */
export function parseTransactionInput(body: unknown, today: string): ParseResult {
  if (typeof body !== "object" || body === null) return { ok: false, error: "格式錯誤" };
  const b = body as Record<string, unknown>;
  const symbol = typeof b.symbol === "string" ? b.symbol.trim().toUpperCase() : "";
  if (!/^[0-9A-Z]{4,6}$/.test(symbol)) return { ok: false, error: "代號格式錯誤" };
  if (!isIsoDate(b.tradeDate)) return { ok: false, error: "日期格式錯誤" };
  if (b.tradeDate > today) return { ok: false, error: "不能輸入未來的日期" };
  if (b.tradeDate < "2000-01-01") return { ok: false, error: "日期太早" };
  if (b.side !== "buy" && b.side !== "sell") return { ok: false, error: "請選擇買進或賣出" };
  const quantity = num(b.quantity);
  if (quantity === null || !Number.isInteger(quantity) || quantity <= 0 || quantity > MAX_QUANTITY) {
    return { ok: false, error: "股數需為正整數" };
  }
  const price = num(b.price);
  if (price === null || price <= 0 || price > MAX_PRICE || decimals(price) > 4) {
    return { ok: false, error: "價格需大於 0，最多四位小數" };
  }
  const fee = money(b.fee);
  const feeRebate = money(b.feeRebate);
  const tax = money(b.tax);
  if (fee === undefined || feeRebate === undefined || tax === undefined) {
    return { ok: false, error: "手續費與稅需為 0 以上的金額" };
  }
  const note = typeof b.note === "string" && b.note.trim() !== "" ? b.note.trim() : null;
  if (note && note.length > MAX_NOTE) return { ok: false, error: `備註最多 ${MAX_NOTE} 字` };
  return {
    ok: true,
    value: {
      symbol,
      tradeDate: b.tradeDate,
      side: b.side,
      quantity,
      price,
      dayTrade: b.dayTrade === true,
      fee,
      feeRebate: fee === null ? null : (feeRebate ?? 0),
      tax: b.side === "buy" ? 0 : tax,
      note,
    },
  };
}

/** Fee, rebate and tax for a trade, honoring hand-entered values. */
export function charges(
  input: Pick<TransactionInput, "side" | "quantity" | "price" | "tradeDate" | "dayTrade" | "fee" | "feeRebate" | "tax">,
  security: { type: string; symbol: string },
  settings: FeeSettings,
): Charges {
  const amount = input.quantity * input.price;
  const auto = brokerFee(amount, input.quantity, settings);
  const rate = taxRate(security.type, security.symbol, input.tradeDate, input.dayTrade);
  const autoTax = input.side === "sell" ? transactionTax(amount, rate) : 0;
  return {
    fee: input.fee ?? auto.fee,
    feeRebate: input.fee === null ? auto.rebate : (input.feeRebate ?? 0),
    tax: input.side === "buy" ? 0 : (input.tax ?? autoTax),
  };
}
