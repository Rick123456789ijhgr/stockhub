import { describe, expect, it } from "vitest";

import { parseJobRequest } from "./job-request-input";

const TODAY = "2026-10-20";

describe("parseJobRequest", () => {
  it("accepts a past trading date for daily_prices", () => {
    expect(parseJobRequest({ job: "daily_prices", params: { date: "2026-07-10" } }, TODAY)).toEqual(
      { job: "daily_prices", params: { date: "2026-07-10" } },
    );
  });

  it("rejects future, impossible and pre-history dates", () => {
    for (const date of ["2026-10-21", "2026-02-30", "2004-01-02", "20260710", 20260710]) {
      expect(parseJobRequest({ job: "daily_prices", params: { date } }, TODAY)).toBeNull();
    }
  });

  it("normalizes symbols and drops unknown params", () => {
    expect(
      parseJobRequest(
        { job: "refetch_stock_prices", params: { symbol: " 00631l ", days: "9999" } },
        TODAY,
      ),
    ).toEqual({ job: "refetch_stock_prices", params: { symbol: "00631L" } });
    expect(parseJobRequest({ job: "refresh_stock_fundamentals", params: {} }, TODAY)).toBeNull();
    expect(
      parseJobRequest({ job: "refresh_stock_fundamentals", params: { symbol: "23;30" } }, TODAY),
    ).toBeNull();
  });

  it("only allows the requestable jobs", () => {
    expect(parseJobRequest({ job: "catch_up_prices", params: { x: 1 } }, TODAY)).toEqual({
      job: "catch_up_prices",
      params: {},
    });
    expect(parseJobRequest({ job: "sync_chips", params: { date: "2026-10-20" } }, TODAY)).toEqual({
      job: "sync_chips",
      params: {},
    });
    for (const job of ["sync_markets", "sync_macro", "sync_news", "check_llm_providers"]) {
      expect(parseJobRequest({ job, params: { series: "SPX" } }, TODAY)).toEqual({ job, params: {} });
    }
    expect(parseJobRequest({ job: "backfill_fundamentals" }, TODAY)).toBeNull();
    expect(parseJobRequest({ job: "backfill_chips" }, TODAY)).toBeNull();
    expect(parseJobRequest({ job: "backfill_markets" }, TODAY)).toBeNull();
    expect(parseJobRequest(null, TODAY)).toBeNull();
    expect(parseJobRequest("daily_prices", TODAY)).toBeNull();
  });
});
