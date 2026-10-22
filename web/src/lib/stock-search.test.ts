import { describe, expect, it } from "vitest";

import { escapeLike, normalizeQuery } from "./stock-search";

describe("normalizeQuery", () => {
  it("turns full-width input into ASCII and trims it", () => {
    expect(normalizeQuery(" ８７８ ")).toBe("878");
    expect(normalizeQuery("ＴＳＭＣ")).toBe("TSMC");
    expect(normalizeQuery("台積電")).toBe("台積電");
  });
});

describe("escapeLike", () => {
  it("takes LIKE wildcards literally", () => {
    expect(escapeLike("878")).toBe("878");
    expect(escapeLike("50%")).toBe("50\\%");
    expect(escapeLike("a_b")).toBe("a\\_b");
    expect(escapeLike("a\\b")).toBe("a\\\\b");
  });
});
