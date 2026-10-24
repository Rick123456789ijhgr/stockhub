import { afterEach, describe, expect, it } from "vitest";

import { memoryEntry, remember, rememberedUrl } from "./nav-memory";

describe("memoryEntry", () => {
  it("remembers top-level pages with their query", () => {
    expect(memoryEntry("/stocks", "tab=volume&type=all")).toEqual([
      "/stocks",
      "/stocks?tab=volume&type=all",
    ]);
    expect(memoryEntry("/market", "")).toEqual(["/market", "/market"]);
  });

  it("ignores sub-pages and pages without state", () => {
    expect(memoryEntry("/stocks/2330", "tab=chips")).toBeNull();
    expect(memoryEntry("/", "")).toBeNull();
    expect(memoryEntry("/more", "")).toBeNull();
  });

  it("does not remember search results", () => {
    expect(memoryEntry("/stocks", "q=2330")).toBeNull();
    expect(memoryEntry("/stocks", "q=")).toBeNull();
  });
});

describe("rememberedUrl", () => {
  afterEach(() => window.localStorage.clear());

  it("returns the page itself until something is remembered", () => {
    expect(rememberedUrl("/stocks")).toBe("/stocks");
    remember("/stocks", "/stocks?tab=volume&type=etf");
    expect(rememberedUrl("/stocks")).toBe("/stocks?tab=volume&type=etf");
    expect(rememberedUrl("/market")).toBe("/market");
  });

  it("never returns a URL of another page", () => {
    window.localStorage.setItem("stockhub.nav-memory", JSON.stringify({ "/stocks": "https://evil.example/" }));
    expect(rememberedUrl("/stocks")).toBe("/stocks");
    window.localStorage.setItem("stockhub.nav-memory", JSON.stringify({ "/stocks": "/stocksx?a=1" }));
    expect(rememberedUrl("/stocks")).toBe("/stocks");
  });

  it("survives unreadable storage", () => {
    window.localStorage.setItem("stockhub.nav-memory", "{not json");
    expect(rememberedUrl("/stocks")).toBe("/stocks");
  });
});
