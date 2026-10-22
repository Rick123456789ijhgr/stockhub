import { describe, expect, it } from "vitest";

import { overlaps, parseEventInput, parseMemberInput, parseMemberKey, parseThemeInput } from "./theme-input";

describe("parseThemeInput", () => {
  it("trims and bounds the name, description optional", () => {
    expect(parseThemeInput({ name: "  AI 伺服器 " })).toEqual({ name: "AI 伺服器", description: null });
    expect(parseThemeInput({ name: "CoWoS", description: "先進封裝" })).toEqual({
      name: "CoWoS",
      description: "先進封裝",
    });
    expect(parseThemeInput({ name: "   " })).toBeNull();
    expect(parseThemeInput({ name: "x".repeat(41) })).toBeNull();
    expect(parseThemeInput({ name: "ok", description: 3 })).toBeNull();
    expect(parseThemeInput(null)).toBeNull();
  });
});

describe("parseMemberInput", () => {
  it("normalizes the symbol and defaults the start to today", () => {
    expect(parseMemberInput({ symbol: " 2330 " }, "2026-10-21")).toEqual({
      symbol: "2330",
      validFrom: "2026-10-21",
      note: null,
    });
    expect(parseMemberInput({ symbol: "00631l", validFrom: "2026-01-02" }, "2026-10-21")?.symbol).toBe(
      "00631L",
    );
    expect(parseMemberInput({ symbol: "23", validFrom: "2026-01-02" }, "2026-10-21")).toBeNull();
    expect(parseMemberInput({ symbol: "2330", validFrom: "2026-02-30" }, "2026-10-21")).toBeNull();
  });
});

describe("parseMemberKey", () => {
  it("requires an end on or after the start when ending a period", () => {
    expect(parseMemberKey({ stockId: 5, validFrom: "2026-01-01" }, false)).toEqual({
      stockId: "5",
      validFrom: "2026-01-01",
    });
    expect(
      parseMemberKey({ stockId: "5", validFrom: "2026-01-01", validTo: "2026-10-21" }, true)?.validTo,
    ).toBe("2026-10-21");
    expect(parseMemberKey({ stockId: "5", validFrom: "2026-01-01", validTo: "2025-12-31" }, true)).toBeNull();
    expect(parseMemberKey({ stockId: "x", validFrom: "2026-01-01" }, false)).toBeNull();
  });
});

describe("overlaps", () => {
  const periods = [{ validFrom: "2026-01-01", validTo: "2026-03-31" }];

  it("detects overlapping membership periods", () => {
    expect(overlaps(periods, "2026-03-31")).toBe(true);
    expect(overlaps(periods, "2026-04-01")).toBe(false);
    expect(overlaps(periods, "2025-06-01", "2025-12-31")).toBe(false);
    expect(overlaps(periods, "2025-06-01", "2026-01-01")).toBe(true);
    expect(overlaps([{ validFrom: "2026-05-01", validTo: null }], "2027-01-01")).toBe(true);
  });
});

describe("parseEventInput", () => {
  it("accepts known kinds and real dates", () => {
    expect(parseEventInput({ date: "2026-12-17", kind: "cbc", title: "央行理監事會" })).toEqual({
      date: "2026-12-17",
      kind: "cbc",
      title: "央行理監事會",
      note: null,
    });
    expect(parseEventInput({ date: "2026-12-17", kind: "boj", title: "x" })).toBeNull();
    expect(parseEventInput({ date: "2026-13-01", kind: "cbc", title: "x" })).toBeNull();
    expect(parseEventInput({ date: "2026-12-17", kind: "cbc", title: " " })).toBeNull();
  });
});
