import { describe, expect, it } from "vitest";

import { financialWindowStart, inFinancialWindow } from "./financial-window";

describe("financial window", () => {
  it("covers this year and the four before, rolling on January 1", () => {
    expect(financialWindowStart("2026-10-22")).toBe("2022-01-01");
    expect(financialWindowStart("2026-12-31")).toBe("2022-01-01");
    expect(financialWindowStart("2027-01-01")).toBe("2023-01-01");
  });

  it("filters rows by their date", () => {
    const rows = [{ d: "2021-12-31" }, { d: "2022-03-31" }, { d: "2026-09-30" }];
    expect(inFinancialWindow(rows, (r) => r.d, "2026-10-22").map((r) => r.d)).toEqual([
      "2022-03-31",
      "2026-09-30",
    ]);
  });
});
