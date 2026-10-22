import { describe, expect, it } from "vitest";

import { activeTab, tabHref } from "./page-tabs";

const TABS = [
  { key: "general", label: "一般" },
  { key: "review", label: "待確認" },
] as const;

describe("activeTab", () => {
  it("returns the requested tab", () => {
    expect(activeTab(TABS, "review")).toBe("review");
  });

  it("falls back to the first tab for missing, unknown or repeated values", () => {
    expect(activeTab(TABS, undefined)).toBe("general");
    expect(activeTab(TABS, "nope")).toBe("general");
    expect(activeTab(TABS, ["review", "general"])).toBe("general");
  });
});

describe("tabHref", () => {
  it("links the first tab to the bare path and the others with ?tab=", () => {
    expect(tabHref("/stocks", "turnover", true)).toBe("/stocks");
    expect(tabHref("/stocks", "gainers", false)).toBe("/stocks?tab=gainers");
  });

  it("keeps the given query on every tab", () => {
    expect(tabHref("/stocks", "turnover", true, { type: "etf" })).toBe("/stocks?type=etf");
    expect(tabHref("/stocks", "gainers", false, { type: "etf" })).toBe("/stocks?type=etf&tab=gainers");
  });
});
