import { describe, expect, it } from "vitest";

import { isFresherThanDaily, isSessionOpen, type LiveQuote } from "./market-hours";

describe("isSessionOpen", () => {
  it("follows Taipei time, not the machine's", () => {
    expect(isSessionOpen(new Date("2026-10-16T01:00:00Z"))).toBe(true); // Fri 09:00
    expect(isSessionOpen(new Date("2026-10-16T05:35:00Z"))).toBe(true); // 13:35
    expect(isSessionOpen(new Date("2026-10-16T05:36:00Z"))).toBe(false);
    expect(isSessionOpen(new Date("2026-10-16T00:59:00Z"))).toBe(false);
    expect(isSessionOpen(new Date("2026-10-17T02:00:00Z"))).toBe(false); // Saturday
  });
});

describe("isFresherThanDaily", () => {
  const quote: LiveQuote = {
    tradeDate: "2026-10-19",
    quoteTime: "2026-10-19T02:00:00Z",
    price: "2430",
    open: null,
    high: null,
    low: null,
    prevClose: "2420",
    volume: "1000",
    bid: null,
    ask: null,
  };

  it("shows today's quote until the daily bar for today exists", () => {
    expect(isFresherThanDaily(quote, "2026-10-16")).toBe(true);
    expect(isFresherThanDaily(quote, "2026-10-19")).toBe(false);
    expect(isFresherThanDaily({ ...quote, price: null }, "2026-10-16")).toBe(false);
    expect(isFresherThanDaily(null, null)).toBe(false);
  });
});
