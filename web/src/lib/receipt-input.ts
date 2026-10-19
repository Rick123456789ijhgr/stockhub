/** Validation of a dividend receipt (safe for client components). */

import { isIsoDate } from "@/lib/transaction-input";

export type ReceiptInput = {
  symbol: string;
  exDate: string;
  actionType: string;
  /** Net cash received; null keeps the estimate. */
  cash: number | null;
  /** Stock dividend shares received; null keeps the estimate. */
  shares: number | null;
  payDate: string | null;
  note: string | null;
};

const ACTION = /^[a-z_]{3,40}$/;

function optionalNumber(value: unknown): number | null | undefined {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1e11 ? n : undefined;
}

/** Parse a PUT body; an error message for the form when invalid. */
export function parseReceiptInput(
  body: unknown,
): { ok: true; value: ReceiptInput } | { ok: false; error: string } {
  if (typeof body !== "object" || body === null) return { ok: false, error: "格式錯誤" };
  const b = body as Record<string, unknown>;
  const symbol = typeof b.symbol === "string" ? b.symbol.trim().toUpperCase() : "";
  if (!/^[0-9A-Z]{4,6}$/.test(symbol)) return { ok: false, error: "代號格式錯誤" };
  if (!isIsoDate(b.exDate)) return { ok: false, error: "除權息日格式錯誤" };
  if (typeof b.actionType !== "string" || !ACTION.test(b.actionType)) {
    return { ok: false, error: "事件類型錯誤" };
  }
  const cash = optionalNumber(b.cash);
  const shares = optionalNumber(b.shares);
  if (cash === undefined || (cash !== null && Math.round(cash * 100) !== cash * 100)) {
    return { ok: false, error: "實收金額需為 0 以上、最多兩位小數" };
  }
  if (shares === undefined || (shares !== null && !Number.isInteger(shares))) {
    return { ok: false, error: "實收股數需為 0 以上的整數" };
  }
  if (cash === null && shares === null) return { ok: false, error: "請輸入實收金額或股數" };
  if (b.payDate !== null && b.payDate !== undefined && b.payDate !== "" && !isIsoDate(b.payDate)) {
    return { ok: false, error: "入帳日格式錯誤" };
  }
  const note = typeof b.note === "string" && b.note.trim() ? b.note.trim().slice(0, 500) : null;
  return {
    ok: true,
    value: {
      symbol,
      exDate: b.exDate,
      actionType: b.actionType,
      cash,
      shares,
      payDate: isIsoDate(b.payDate) ? b.payDate : null,
      note,
    },
  };
}
