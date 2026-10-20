// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  bandMultiples,
  metricValues,
  percentileRank,
  riverBands,
  shiftYears,
  summarize,
  valuationSeries,
  windowYears,
  type Metric,
} from "./valuation";

type Snake = Record<string, number | string | null>;
const fixture = JSON.parse(
  readFileSync(new URL("../../../testdata/valuation.json", import.meta.url), "utf-8"),
) as {
  input: { prices: Snake[]; quarters: Snake[]; dividends: Snake[] };
  expected: {
    series: Snake[];
    summaries: Record<string, Snake>;
    pe_multiples: number[];
    pb_multiples: number[];
    pe_bands_tail: (number | null)[][];
    shift_years: Record<string, string>;
  };
};

const prices = fixture.input.prices.map((p) => ({ date: String(p.date), close: Number(p.close) }));
const quarters = fixture.input.quarters.map((q) => ({
  periodEnd: String(q.period_end),
  availableDate: String(q.available_date),
  epsTtm: q.eps_ttm === null ? null : Number(q.eps_ttm),
  bvps: q.bvps === null ? null : Number(q.bvps),
}));
const dividends = fixture.input.dividends.map((d) => ({
  exDate: String(d.ex_date),
  cash: Number(d.cash),
}));

function close(actual: number | null, expected: number | string | null) {
  if (expected === null) expect(actual).toBeNull();
  else expect(actual).toBeCloseTo(Number(expected), 10);
}

describe("valuation (shared fixture with Python)", () => {
  const series = valuationSeries(prices, quarters, dividends);

  it("matches the per-day series", () => {
    expect(series).toHaveLength(fixture.expected.series.length);
    series.forEach((p, i) => {
      const e = fixture.expected.series[i];
      expect(p.date).toBe(e.date);
      close(p.epsTtm, e.eps_ttm);
      close(p.bvps, e.bvps);
      close(p.pe, e.pe);
      close(p.pb, e.pb);
      close(p.dividendTtm, e.dividend_ttm);
      close(p.dividendYield, e.dividend_yield);
    });
  });

  it("matches the summaries", () => {
    const names: Record<string, Metric> = { pe: "pe", pb: "pb", dividend_yield: "dividendYield" };
    for (const [key, expected] of Object.entries(fixture.expected.summaries)) {
      const [metric, years] = [key.slice(0, key.lastIndexOf("_")), Number(key.slice(-2, -1))];
      const got = summarize(series, names[metric], years);
      close(got.current, expected.current);
      close(got.percentile, expected.percentile);
      close(got.low, expected.low);
      close(got.median, expected.median);
      close(got.high, expected.high);
      expect(got.count).toBe(expected.count);
    }
  });

  it("matches the river multiples and bands", () => {
    const pe = bandMultiples(metricValues(windowYears(series, 2), "pe"));
    const pb = bandMultiples(metricValues(windowYears(series, 2), "pb"));
    pe.forEach((m, i) => close(m, fixture.expected.pe_multiples[i]));
    pb.forEach((m, i) => close(m, fixture.expected.pb_multiples[i]));
    riverBands(series.slice(-5), "pe", pe).forEach((row, i) =>
      row.forEach((v, j) => close(v, fixture.expected.pe_bands_tail[i][j])),
    );
  });

  it("shifts leap days like Python", () => {
    for (const [from, to] of Object.entries(fixture.expected.shift_years)) {
      expect(shiftYears(from, -2)).toBe(to);
    }
  });

  it("ranks ties at the midpoint", () => {
    expect(percentileRank([1, 2, 2, 3], 2)).toBe(0.5);
    expect(percentileRank([], 1)).toBeNull();
  });
});
