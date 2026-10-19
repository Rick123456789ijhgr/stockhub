import { describe, expect, it } from "vitest";

import {
  backfillProgress,
  cellState,
  type DayCoverage,
  fetchedRange,
  gapDays,
  summarizeYears,
  yearGrid,
} from "./coverage-grid";

const day = (date: string, isTradingDay: boolean, twse = 0, tpex = 0): DayCoverage => ({
  date,
  isTradingDay,
  twse,
  tpex,
});

const DAYS = [
  day("2026-10-08", true), // before the fetched range
  day("2026-10-09", false), // holiday
  day("2026-10-12", true, 1300, 1000),
  day("2026-10-13", true), // gap inside the range
  day("2026-10-14", true, 1300, 0), // one market only
  day("2026-10-15", true, 1300, 1000),
  day("2026-10-16", true), // today, not published yet
];
const TODAY = "2026-10-16";

describe("coverage cell states", () => {
  it("classifies every kind of day", () => {
    const range = fetchedRange(DAYS);
    expect(range).toEqual({ first: "2026-10-12", last: "2026-10-15" });
    expect(DAYS.map((d) => cellState(d, TODAY, range))).toEqual([
      "notFetched",
      "closed",
      "full",
      "gap",
      "partial",
      "full",
      "future",
    ]);
  });

  it("does not flag days a running backfill has not reached yet", () => {
    const range = fetchedRange(DAYS);
    const pending = [{ from: "2026-10-13", to: "2026-10-13" }];
    expect(cellState(DAYS[3], TODAY, range, pending)).toBe("notFetched");
    expect(gapDays(DAYS, TODAY, pending).map((d) => d.date)).toEqual(["2026-10-14"]);
  });

  it("has no range before any data exists", () => {
    expect(fetchedRange([day("2026-10-12", true)])).toBeNull();
    expect(cellState(day("2026-10-12", true), TODAY, null)).toBe("notFetched");
  });
});

describe("yearGrid", () => {
  it("lays out 12 months × 31 days with nulls for impossible dates", () => {
    const grid = yearGrid(2026, DAYS, TODAY, fetchedRange(DAYS));
    expect(grid).toHaveLength(12);
    expect(grid[1].cells[28]).toBeNull(); // 2026-02-29
    expect(grid[3].cells[30]).toBeNull(); // 04-31
    expect(grid[9].cells[11]?.state).toBe("full"); // 10-12
    expect(grid[9].cells[12]?.state).toBe("gap"); // 10-13
    // Dates missing from the calendar render as closed (e.g. far past seed gaps).
    expect(grid[0].cells[0]?.state).toBe("closed");
  });
});

describe("summaries", () => {
  it("counts trading days, fetched days and gaps per year", () => {
    expect(summarizeYears(DAYS, TODAY)).toEqual([
      { year: 2026, tradingDays: 5, fetched: 2, partial: 1, gaps: 1 },
    ]);
  });

  it("lists gap and partial days for the table view", () => {
    expect(gapDays(DAYS, TODAY).map((d) => d.date)).toEqual(["2026-10-13", "2026-10-14"]);
  });
});

describe("backfillProgress", () => {
  const tradingDays = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"];

  it("reports share done and an ETA from the elapsed rate", () => {
    const progress = backfillProgress(
      tradingDays,
      "2026-10-14",
      "2026-10-18T10:00:00Z",
      new Date("2026-10-18T10:00:06Z"),
    );
    expect(progress).toEqual({ done: 2, total: 4, percent: 50, etaSeconds: 6 });
  });

  it("has no ETA before the first day or after the last", () => {
    expect(backfillProgress(tradingDays, null, "2026-10-18T10:00:00Z", new Date()).etaSeconds).toBeNull();
    expect(
      backfillProgress(tradingDays, "2026-10-16", "2026-10-18T10:00:00Z", new Date()).percent,
    ).toBe(100);
  });
});
