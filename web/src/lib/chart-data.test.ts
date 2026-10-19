import { describe, expect, it } from "vitest";

import {
  adjustedChangePercent,
  type ChartBar,
  needsFullHistory,
  type RangeKey,
  rangeStartIndex,
  toOhlc,
} from "./chart-data";

// 0050 around its 1 -> 4 split on 2025-06-18 (factor = 47.16 / 188.65 before it).
const SPLIT = 47.16 / 188.65;
const bars: ChartBar[] = [
  ["2024-06-17", 180, 190, 179, 188, 1000, SPLIT],
  ["2025-06-17", 188, 190, 187, 188.65, 1000, SPLIT],
  ["2025-06-18", 47.2, 47.5, 47, 47.3, 4000, 1],
  ["2025-12-31", 50, 51, 49, 50, 4000, 1],
];

describe("toOhlc", () => {
  it("keeps raw prices", () => {
    expect(toOhlc(bars, "raw")[1].close).toBe(188.65);
  });

  it("puts old prices on today's share basis", () => {
    expect(toOhlc(bars, "adjusted")[1].close).toBeCloseTo(47.16, 10);
    expect(toOhlc(bars, "adjusted")[2].close).toBe(47.3);
  });
});

describe("adjustedChangePercent", () => {
  it("measures the split day against the reference price, not the old close", () => {
    expect(adjustedChangePercent(bars, 2)).toBeCloseTo((47.3 / 47.16 - 1) * 100, 10);
  });

  it("is null without a previous bar", () => {
    expect(adjustedChangePercent(bars, 0)).toBeNull();
  });
});

describe("rangeStartIndex", () => {
  it("counts back from the latest bar", () => {
    expect(rangeStartIndex(bars, "6M")).toBe(3);
    expect(rangeStartIndex(bars, "1Y")).toBe(1);
    expect(rangeStartIndex(bars, "ALL")).toBe(0);
    expect(rangeStartIndex([], "1Y")).toBe(0);
  });
});

describe("needsFullHistory", () => {
  it("is only needed beyond the recent three years", () => {
    expect(["6M", "1Y", "3Y"].map((r) => needsFullHistory(r as RangeKey))).toEqual([
      false,
      false,
      false,
    ]);
    expect(needsFullHistory("5Y")).toBe(true);
    expect(needsFullHistory("ALL")).toBe(true);
  });
});
