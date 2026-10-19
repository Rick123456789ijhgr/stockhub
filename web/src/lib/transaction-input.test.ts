import { describe, expect, it } from "vitest";

import { DEFAULT_FEES } from "./portfolio";
import { charges, isIsoDate, parseTransactionInput } from "./transaction-input";

const TODAY = "2026-10-19";
const base = {
  symbol: " 2330 ",
  tradeDate: "2026-10-16",
  side: "sell",
  quantity: "1000",
  price: "1450.5",
  dayTrade: false,
  fee: "",
  tax: null,
  note: "  ",
};

describe("parseTransactionInput", () => {
  it("normalizes a valid body", () => {
    expect(parseTransactionInput(base, TODAY)).toEqual({
      ok: true,
      value: {
        symbol: "2330",
        tradeDate: "2026-10-16",
        side: "sell",
        quantity: 1000,
        price: 1450.5,
        dayTrade: false,
        fee: null,
        feeRebate: null,
        tax: null,
        note: null,
      },
    });
  });

  it("keeps hand-entered charges and forces no tax on buys", () => {
    const r = parseTransactionInput({ ...base, side: "buy", fee: "20", tax: "5" }, TODAY);
    expect(r.ok && r.value).toMatchObject({ fee: 20, feeRebate: 0, tax: 0 });
  });

  it.each([
    [{ symbol: "23" }, "代號格式錯誤"],
    [{ tradeDate: "2026-02-30" }, "日期格式錯誤"],
    [{ tradeDate: "2026-10-20" }, "不能輸入未來的日期"],
    [{ side: "short" }, "請選擇買進或賣出"],
    [{ quantity: "1.5" }, "股數需為正整數"],
    [{ quantity: 0 }, "股數需為正整數"],
    [{ price: "0" }, "價格需大於 0，最多四位小數"],
    [{ price: "1.23456" }, "價格需大於 0，最多四位小數"],
    [{ fee: "-1" }, "手續費與稅需為 0 以上的金額"],
    [{ tax: "1.234" }, "手續費與稅需為 0 以上的金額"],
  ])("rejects %o", (patch, error) => {
    expect(parseTransactionInput({ ...base, ...patch }, TODAY)).toEqual({ ok: false, error });
  });
});

describe("charges", () => {
  const input = {
    side: "sell" as const,
    quantity: 1000,
    price: 100,
    tradeDate: "2026-10-16",
    dayTrade: false,
    fee: null,
    feeRebate: null,
    tax: null,
  };
  const stock = { type: "stock", symbol: "2330" };

  it("fills fee and tax automatically", () => {
    expect(charges(input, stock, DEFAULT_FEES)).toEqual({ fee: 142, feeRebate: 0, tax: 300 });
    expect(charges({ ...input, dayTrade: true }, stock, DEFAULT_FEES).tax).toBe(150);
    expect(charges(input, { type: "etf", symbol: "00679B" }, DEFAULT_FEES).tax).toBe(0);
    expect(charges({ ...input, side: "buy" }, stock, DEFAULT_FEES).tax).toBe(0);
  });

  it("estimates the rebate in rebate mode, and keeps hand-entered values", () => {
    const rebate = { ...DEFAULT_FEES, discount: 0.5, discountMode: "rebate" as const };
    expect(charges(input, stock, rebate)).toEqual({ fee: 142, feeRebate: 71, tax: 300 });
    expect(charges({ ...input, fee: 50, feeRebate: 0, tax: 1 }, stock, rebate)).toEqual({
      fee: 50,
      feeRebate: 0,
      tax: 1,
    });
  });
});

it("isIsoDate", () => {
  expect(isIsoDate("2026-10-19")).toBe(true);
  expect(isIsoDate("2026-13-01")).toBe(false);
  expect(isIsoDate("20261019")).toBe(false);
});
