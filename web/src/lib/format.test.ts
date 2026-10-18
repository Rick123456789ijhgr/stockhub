import { describe, expect, it } from "vitest";

import {
  formatDuration,
  formatHundredMillion,
  formatInteger,
  formatLots,
  formatPrice,
  formatTaipeiDateTime,
  summarizeError,
} from "./format";

describe("formatTaipeiDateTime", () => {
  it("converts UTC to Asia/Taipei for display", () => {
    expect(formatTaipeiDateTime("2026-10-17T17:37:40Z")).toBe("2026/10/18 01:37:40");
    expect(formatTaipeiDateTime(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it.each([
    [null, "—"],
    [850, "850 ms"],
    [12_345, "12.3 s"],
    [245_000, "4 分 05 秒"],
    [3_720_000, "1 小時 02 分"],
  ])("%s -> %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe("summarizeError", () => {
  it("collapses lines and truncates", () => {
    expect(summarizeError("\n資料落後：\n  prices_daily …\n")).toBe("資料落後： prices_daily …");
    expect(summarizeError("x".repeat(200), 10)).toBe(`${"x".repeat(9)}…`);
    expect(summarizeError(null)).toBeNull();
  });
});

describe("formatInteger", () => {
  it("adds thousands separators", () => {
    expect(formatInteger(1234567)).toBe("1,234,567");
    expect(formatInteger("42")).toBe("42");
    expect(formatInteger(null)).toBe("—");
  });
});

describe("market number formats", () => {
  it("formats prices, lots and 億", () => {
    expect(formatPrice("2420.0000")).toBe("2,420.00");
    expect(formatPrice(null)).toBe("—");
    expect(formatLots("43046982")).toBe("43,047");
    expect(formatHundredMillion("104583063462")).toBe("1,045.83");
  });
});
