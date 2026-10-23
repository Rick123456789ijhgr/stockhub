import { describe, expect, it } from "vitest";

import {
  chartClock,
  chartSeconds,
  type IntradayDay,
  intradayBase,
  intradayLine,
  showIntraday,
  withDailyReference,
} from "./intraday";

const day: IntradayDay = {
  tradeDate: "2026-10-16",
  prevClose: "2440",
  points: [
    { at: "2026-10-16T01:00:30Z", price: "2425" },
    { at: "2026-10-16T01:00:00Z", price: "2430" },
    { at: "2026-10-16T01:00:30.400Z", price: "2426" }, // same second: the later one wins
  ],
};

describe("chart time", () => {
  it("reads as Taipei time on the chart's UTC axis", () => {
    expect(chartClock(chartSeconds("2026-10-16T01:00:30Z"))).toBe("09:00:30");
    expect(chartClock(chartSeconds("2026-10-16T05:30:00Z"))).toBe("13:30:00");
  });
});

describe("intradayLine", () => {
  it("sorts by time and keeps one point per second", () => {
    const line = intradayLine(day);
    expect(line.map((p) => chartClock(p.time))).toEqual(["09:00:00", "09:00:30"]);
    expect(line.map((p) => p.value)).toEqual([2430, 2426]);
  });
});

describe("intradayBase", () => {
  it("uses the reference price, else the first sample", () => {
    expect(intradayBase(day)).toBe(2440);
    expect(intradayBase({ ...day, prevClose: null })).toBe(2425);
    expect(intradayBase({ ...day, prevClose: null, points: [] })).toBeNull();
  });
});

describe("showIntraday", () => {
  it("shows the sampled day unless a newer daily bar exists", () => {
    expect(showIntraday(day, "2026-10-15")).toBe(true);
    expect(showIntraday(day, "2026-10-16")).toBe(true); // after the close, same session
    expect(showIntraday(day, "2026-10-19")).toBe(false);
    expect(showIntraday(day, null)).toBe(true);
    expect(showIntraday({ ...day, points: [] }, null)).toBe(false);
    expect(showIntraday(null, null)).toBe(false);
  });
});

describe("withDailyReference", () => {
  it("takes the same day's rebased previous close only when the day has none", () => {
    const bare = { ...day, prevClose: null };
    expect(withDailyReference(bare, { tradeDate: "2026-10-16", prevClose: "2420" }).prevClose).toBe("2420");
    expect(withDailyReference(bare, { tradeDate: "2026-10-15", prevClose: "2420" }).prevClose).toBeNull();
    expect(withDailyReference(day, { tradeDate: "2026-10-16", prevClose: "1" }).prevClose).toBe("2440");
    expect(withDailyReference(bare, undefined)).toBe(bare);
  });
});
