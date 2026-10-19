import { describe, expect, it } from "vitest";

import { parseReceiptInput } from "./receipt-input";

const base = { symbol: "0056", exDate: "2026-07-16", actionType: "cash_dividend", cash: "4310" };

describe("parseReceiptInput", () => {
  it("accepts cash only, shares only, or both", () => {
    expect(parseReceiptInput(base)).toEqual({
      ok: true,
      value: { ...base, cash: 4310, shares: null, payDate: null, note: null },
    });
    const both = parseReceiptInput({ ...base, cash: "", shares: "104", payDate: "2026-08-12" });
    expect(both.ok && both.value).toMatchObject({ cash: null, shares: 104, payDate: "2026-08-12" });
  });

  it.each([
    [{ cash: "", shares: "" }, "請輸入實收金額或股數"],
    [{ cash: "-1" }, "實收金額需為 0 以上、最多兩位小數"],
    [{ cash: "1.234" }, "實收金額需為 0 以上、最多兩位小數"],
    [{ shares: "1.5" }, "實收股數需為 0 以上的整數"],
    [{ exDate: "2026-02-30" }, "除權息日格式錯誤"],
    [{ actionType: "DROP TABLE" }, "事件類型錯誤"],
    [{ payDate: "soon" }, "入帳日格式錯誤"],
  ])("rejects %o", (patch, error) => {
    expect(parseReceiptInput({ ...base, ...patch })).toEqual({ ok: false, error });
  });
});
