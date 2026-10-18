// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { ema, kd, macd, rsi, type Series, sma } from "./indicators";

type Fixture = {
  input: { high: number[]; low: number[]; close: number[] };
  expected: Record<string, (number | null)[]>;
};

// Shared with py/tests/engine/test_indicators.py (CLAUDE.md rule 11).
const fixture = JSON.parse(
  readFileSync(new URL("../../../testdata/indicators.json", import.meta.url), "utf-8"),
) as Fixture;

function expectSeries(actual: Series, expected: (number | null)[]) {
  expect(actual).toHaveLength(expected.length);
  actual.forEach((value, i) => {
    const want = expected[i];
    if (want === null) {
      expect(value, `index ${i}`).toBeNull();
    } else {
      expect(value, `index ${i}`).not.toBeNull();
      expect(Math.abs((value as number) - want), `index ${i}`).toBeLessThanOrEqual(
        1e-12 * Math.max(1, Math.abs(want)),
      );
    }
  });
}

describe("indicators match the Python reference", () => {
  const { high, low, close } = fixture.input;
  const m = macd(close);
  const k = kd(high, low, close);
  const actual: Record<string, Series> = {
    sma5: sma(close, 5),
    sma20: sma(close, 20),
    sma60: sma(close, 60),
    ema12: ema(close, 12),
    macd_dif: m.dif,
    macd_signal: m.signal,
    macd_histogram: m.histogram,
    kd_k: k.k,
    kd_d: k.d,
    rsi14: rsi(close),
  };

  it("covers every expected series", () => {
    expect(Object.keys(actual).sort()).toEqual(Object.keys(fixture.expected).sort());
  });

  for (const name of Object.keys(fixture.expected)) {
    it(name, () => expectSeries(actual[name], fixture.expected[name]));
  }
});

describe("hand-checked cases", () => {
  it("sma", () => {
    expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });

  it("ema is seeded with the sma", () => {
    expect(ema([1, 2, 3, 4], 3)).toEqual([null, null, 2, 3]);
  });

  it("rsi extremes", () => {
    expect(rsi([1, 2, 3, 4], 3)[3]).toBe(100);
    expect(rsi([5, 5, 5, 5], 3)[3]).toBe(50);
    expect(rsi([10, 11, 10, 11, 12], 2)[3]).toBeCloseTo(75);
  });

  it("kd on a flat range stays at 50", () => {
    expect(kd([10, 10], [10, 10], [10, 10], 1).k).toEqual([50, 50]);
  });
});
