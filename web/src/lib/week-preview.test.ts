import { describe, expect, it } from "vitest";

import type { LiveQuote } from "./market-hours";
import type { DailyBarRow } from "./stocks";
import { weekPreview } from "./week-preview";

function bar(tradeDate: string, close: number, prevClose: number | null, adjFactor = 1): DailyBarRow {
  return {
    tradeDate,
    open: String(close - 1),
    high: String(close + 2),
    low: String(close - 2),
    close: String(close),
    prevClose: prevClose === null ? null : String(prevClose),
    volume: "1000",
    turnover: "100000",
    adjFactor: String(adjFactor),
  };
}

// Newest first, as getRecentBars returns them.
const bars = [
  bar("2026-10-22", 110, 105),
  bar("2026-10-21", 105, 104),
  bar("2026-10-20", 104, 102),
  bar("2026-10-17", 102, 101),
  bar("2026-10-16", 101, 100),
  bar("2026-10-15", 100, 99),
];

const quote: LiveQuote = {
  tradeDate: "2026-10-23",
  quoteTime: "2026-10-23T03:00:00Z",
  price: "121",
  open: "111",
  high: "122",
  low: "110",
  prevClose: "110",
  volume: "5000",
  bid: null,
  ask: null,
};

describe("weekPreview", () => {
  it("takes the last five daily candles, oldest first, against the close before them", () => {
    const p = weekPreview(bars, null);
    expect(p.candles.map((c) => c.date)).toEqual([
      "2026-10-16",
      "2026-10-17",
      "2026-10-20",
      "2026-10-21",
      "2026-10-22",
    ]);
    expect(p.base).toBe(100);
    expect(p.last).toBe(110);
    expect(p.change).toBeCloseTo(5);
    expect(p.weekPercent).toBeCloseTo(10);
    expect(p.live).toBe(false);
  });

  it("uses today's live quote as the last candle", () => {
    const p = weekPreview(bars, quote);
    expect(p.candles).toHaveLength(5);
    expect(p.candles[0]!.date).toBe("2026-10-17");
    expect(p.candles.at(-1)).toEqual({ date: "2026-10-23", open: 111, high: 122, low: 110, close: 121 });
    expect(p.base).toBe(101);
    expect(p.change).toBeCloseTo(11);
    expect(p.percent).toBeCloseTo(10);
    expect(p.live).toBe(true);
  });

  it("puts older bars on the latest basis across an ex-dividend day", () => {
    // 10/20 went ex-dividend by 10: older raw prices are scaled down so the line is smooth.
    const exBars = [
      bar("2026-10-22", 92, 91),
      bar("2026-10-21", 91, 90),
      bar("2026-10-20", 90, 90, 1), // reference price 90 (rebased from 100)
      bar("2026-10-17", 100, 99, 0.9),
      bar("2026-10-16", 99, 98, 0.9),
      bar("2026-10-15", 98, 97, 0.9),
    ];
    const p = weekPreview(exBars, null);
    [89.1, 90, 90, 91, 92].forEach((close, i) => expect(p.candles[i]!.close).toBeCloseTo(close));
    expect(p.base).toBeCloseTo(98 * 0.9);
  });

  it("ignores a stale quote from before the latest bar", () => {
    const p = weekPreview(bars, { ...quote, tradeDate: "2026-10-22" });
    expect(p.live).toBe(false);
    expect(p.last).toBe(110);
  });
});
