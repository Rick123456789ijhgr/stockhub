import { describe, expect, it } from "vitest";

import { isFresherThanDaily, isSessionOpen, type LiveQuote, sessionPhase, taipeiToday } from "./market-hours";

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

describe("taipeiToday", () => {
  it("rolls over at Taipei midnight", () => {
    expect(taipeiToday(new Date("2026-10-18T15:59:00Z"))).toBe("2026-10-18");
    expect(taipeiToday(new Date("2026-10-18T16:00:00Z"))).toBe("2026-10-19");
  });
});

describe("sessionPhase", () => {
  const friday = { date: "2026-10-16", tradingDay: true };
  const at = (utc: string) => sessionPhase(new Date(utc), friday);

  it("walks through the Taipei session on the 08:30–13:30 rail", () => {
    expect(at("2026-10-16T00:00:00Z")).toEqual({ phase: "pre", progress: 0 }); // 08:00
    expect(at("2026-10-16T00:45:00Z")).toEqual({ phase: "trial", progress: 0.05 }); // 08:45
    expect(at("2026-10-16T01:00:00Z")).toEqual({ phase: "continuous", progress: 0.1 }); // 09:00
    expect(at("2026-10-16T05:25:00Z").phase).toBe("closingAuction"); // 13:25
    expect(at("2026-10-16T05:30:00Z")).toEqual({ phase: "closed", progress: 1 }); // 13:30
  });

  it("follows the calendar, and weekends once the date has passed", () => {
    const holiday = { date: "2026-10-16", tradingDay: false };
    expect(sessionPhase(new Date("2026-10-16T02:00:00Z"), holiday).phase).toBe("holiday");
    // Left open into Saturday: no calendar row for that date, the weekend rule applies.
    expect(sessionPhase(new Date("2026-10-17T02:00:00Z"), friday).phase).toBe("holiday");
    // Unknown calendar row today: weekdays trade.
    expect(sessionPhase(new Date("2026-10-16T02:00:00Z"), { ...friday, tradingDay: null }).phase).toBe(
      "continuous",
    );
  });
});
