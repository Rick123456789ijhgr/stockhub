import { describe, expect, it } from "vitest";

import { priceChange } from "./price";

describe("priceChange", () => {
  it("computes close-to-close change and percent", () => {
    const result = priceChange("2420.0000", "2440.0000");
    expect(result?.change).toBeCloseTo(-20);
    expect(result?.percent).toBeCloseTo(-0.8197, 3);
  });

  it("is null when a side is missing or zero", () => {
    expect(priceChange(null, "10")).toBeNull();
    expect(priceChange("10", null)).toBeNull();
    expect(priceChange("10", "0")).toBeNull();
  });
});
