import { describe, expect, it } from "vitest";

import { axisFormat, formatValue, periodLabel } from "./chart-format";

describe("chart-format", () => {
  it("labels quarters, months and days", () => {
    expect(periodLabel("2026-06-30", "quarter")).toBe("2026Q2");
    expect(periodLabel("2026-12-31", "quarter")).toBe("2026Q4");
    expect(periodLabel("2026-09-01", "month")).toBe("2026/09");
    expect(periodLabel("2026-10-20", "day")).toBe("2026/10/20");
  });

  it("formats values by kind and blanks missing ones", () => {
    expect(formatValue(0.6772, "percent")).toBe("67.7%");
    expect(formatValue(27.9, "ratio")).toBe("27.9 倍");
    expect(formatValue(1270380000000, "hundredMillion")).toBe("12,703.8 億");
    expect(formatValue(27.25, "eps")).toBe("27.25");
    expect(formatValue(null, "percent")).toBe("—");
    expect(formatValue(Number.NaN, "eps")).toBe("—");
    expect(axisFormat(0.5, "percent")).toBe("50%");
    expect(formatValue(-22_371_830, "lots")).toBe("-22,372 張");
    expect(axisFormat(-22_371_830, "lots")).toBe("-2.2萬");
    expect(axisFormat(4_500_000, "lots")).toBe("4500");
    expect(formatValue(0.456, "score")).toBe("+0.46");
    expect(formatValue(-0.4, "score")).toBe("-0.40");
    expect(axisFormat(-0.5, "score")).toBe("-0.5");
    expect(formatValue(1234, "count")).toBe("1,234 則");
  });
});
