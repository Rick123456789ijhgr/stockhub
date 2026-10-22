/** Exchange of a listing; client-safe (lib/stocks.ts is server-only and re-exports these). */
export type Market = "twse" | "tpex";

export const MARKET_LABEL: Record<Market, string> = { twse: "上市", tpex: "上櫃" };
