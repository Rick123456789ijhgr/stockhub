import { describe, expect, it } from "vitest";

import {
  changesInPoints,
  formatSeriesValue,
  latestChange,
  percentToFraction,
  spread,
  yearOverYear,
} from "./market-series";

describe("latestChange", () => {
  const pts = [
    { date: "2026-10-16", value: 100 },
    { date: "2026-10-19", value: 102, label: "x" },
  ];

  it("measures prices as a fraction and rates in points", () => {
    expect(latestChange(pts, false)).toMatchObject({
      date: "2026-10-19",
      value: 102,
      label: "x",
      prevDate: "2026-10-16",
    });
    expect(latestChange(pts, false)?.change).toBeCloseTo(0.02);
    expect(latestChange(pts, true)?.change).toBeCloseTo(2);
    expect(latestChange([pts[0]], false)?.change).toBeNull();
    expect(latestChange([], false)).toBeNull();
  });

  it("knows which units move in points", () => {
    expect(changesInPoints({ unit: "percent" })).toBe(true);
    expect(changesInPoints({ unit: "point" })).toBe(false);
  });
});

describe("yearOverYear", () => {
  it("compares the same calendar month a year earlier", () => {
    const yoy = yearOverYear([
      { date: "2025-08-01", value: 100 },
      { date: "2025-09-01", value: 101 },
      { date: "2026-08-01", value: 103 },
    ]);
    expect(yoy).toHaveLength(1);
    expect(yoy[0].date).toBe("2026-08-01");
    expect(yoy[0].value).toBeCloseTo(0.03);
  });
});

describe("spread", () => {
  it("subtracts on common dates only", () => {
    const s = spread(
      [
        { date: "a", value: 5 },
        { date: "b", value: 4.5 },
      ],
      [{ date: "b", value: 4 }],
    );
    expect(s).toEqual([{ date: "b", value: 0.5 }]);
  });
});

describe("formatting", () => {
  it("formats by unit", () => {
    expect(formatSeriesValue(5.244, "percent")).toBe("5.24%");
    expect(formatSeriesValue(41, "score")).toBe("41 分");
    expect(formatSeriesValue(30.1234, "TWD")).toBe("30.123");
    expect(formatSeriesValue(48353.49, "point")).toBe("48,353");
    expect(formatSeriesValue(18.5, "point")).toBe("18.50");
    expect(percentToFraction([{ date: "a", value: 5 }])).toEqual([{ date: "a", value: 0.05 }]);
  });
});
