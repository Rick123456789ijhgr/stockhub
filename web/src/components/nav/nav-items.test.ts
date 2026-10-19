import { describe, expect, it } from "vitest";

import { isActive, isMoreActive, NAV_ITEMS } from "./nav-items";

describe("navigation", () => {
  it("has nine sections, four of them in the mobile bar", () => {
    expect(NAV_ITEMS.map((i) => i.label)).toEqual([
      "首頁",
      "持股",
      "個股",
      "自選",
      "市場",
      "篩選器",
      "回測",
      "狀態",
      "設定",
    ]);
    expect(NAV_ITEMS.filter((i) => i.primary)).toHaveLength(4);
  });

  it("matches the active section by path prefix", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/status", "/")).toBe(false);
    expect(isActive("/stocks/2330", "/stocks")).toBe(true);
    expect(isActive("/stocksx", "/stocks")).toBe(false);
  });

  it("highlights 更多 for pages only reachable through it", () => {
    expect(isMoreActive("/more")).toBe(true);
    expect(isMoreActive("/status")).toBe(true);
    expect(isMoreActive("/watchlist")).toBe(true);
    expect(isMoreActive("/portfolio")).toBe(false);
  });
});
