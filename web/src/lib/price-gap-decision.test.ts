import { describe, expect, it } from "vitest";

import { describeShareRatio, parseGapDecision } from "./price-gap-decision";

describe("parseGapDecision", () => {
  it("accepts a confirmation with a ratio and type", () => {
    expect(parseGapDecision({ decision: "confirm", ratio: "4", actionType: "split" })).toEqual({
      kind: "confirm",
      ratio: 4,
      actionType: "split",
    });
    expect(
      parseGapDecision({ decision: "confirm", ratio: 0.1, actionType: "reverse_split" }),
    ).toEqual({ kind: "confirm", ratio: 0.1, actionType: "reverse_split" });
  });

  it("accepts a dismissal without other fields", () => {
    expect(parseGapDecision({ decision: "dismiss" })).toEqual({ kind: "dismiss" });
  });

  it.each([
    null,
    "confirm",
    {},
    { decision: "confirm", ratio: 4 },
    { decision: "confirm", ratio: 4, actionType: "cash_dividend" },
    { decision: "confirm", ratio: "abc", actionType: "split" },
    { decision: "confirm", ratio: 1, actionType: "split" },
    { decision: "confirm", ratio: 0.01, actionType: "split" },
    { decision: "confirm", ratio: 51, actionType: "split" },
    { decision: "confirm", ratio: Number.POSITIVE_INFINITY, actionType: "split" },
  ])("rejects %j", (body) => {
    expect(parseGapDecision(body)).toBeNull();
  });
});

describe("describeShareRatio", () => {
  it("describes splits and merges", () => {
    expect(describeShareRatio(4)).toBe("1 股變 4 股（價格 ÷ 4）");
    expect(describeShareRatio(0.1)).toBe("10 股併成 1 股（價格 × 10）");
    expect(describeShareRatio(2.5)).toBe("1 股變 2.5 股（價格 ÷ 2.5）");
  });
});
