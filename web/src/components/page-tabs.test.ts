import { describe, expect, it } from "vitest";

import { activeTab } from "./page-tabs";

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
