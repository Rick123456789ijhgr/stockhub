import { describe, expect, it } from "vitest";

import { barPercent, flowScale, formatYi } from "./flow-chart";

describe("flow chart geometry", () => {
  it("scales to the largest absolute value, skipping missing ones", () => {
    expect(flowScale([-81.66e9, 8.87e9, null, -27.38e9])).toBe(81.66e9);
    expect(flowScale([])).toBe(0);
    expect(flowScale([null])).toBe(0);
  });

  it("draws bars as a share of the scale, with a visible minimum", () => {
    expect(barPercent(-50, 100)).toBe(50);
    expect(barPercent(100, 100)).toBe(100);
    expect(barPercent(0.1, 100)).toBe(1.5);
    expect(barPercent(0, 100)).toBe(0);
    expect(barPercent(null, 100)).toBe(0);
    expect(barPercent(5, 0)).toBe(0);
  });

  it("prints 億 with a sign", () => {
    expect(formatYi(-100_160_000_000)).toBe("-1,001.6");
    expect(formatYi(8_870_000_000)).toBe("+88.7");
    expect(formatYi(1_000_000)).toBe("0.0");
  });
});
