import { describe, expect, it } from "vitest";

import { hexToOklch, parseBrandColor, priceColorClash } from "./brand-color";

describe("brand color", () => {
  it("keeps only #rrggbb values", () => {
    expect(parseBrandColor("#2563EB")).toBe("#2563eb");
    expect(parseBrandColor("#abc")).toBeNull();
    expect(parseBrandColor("blue")).toBeNull();
    expect(parseBrandColor(null)).toBeNull();
  });

  it("converts hex to OKLCH", () => {
    const white = hexToOklch("#ffffff");
    expect(white.l).toBeCloseTo(1, 3);
    expect(white.c).toBeCloseTo(0, 3);
    // Reference values from the CSS Color 4 sample code (oklch(62.8% 0.2577 29.23)).
    const red = hexToOklch("#ff0000");
    expect(red.l).toBeCloseTo(0.628, 2);
    expect(red.c).toBeCloseTo(0.2577, 2);
    expect(red.h).toBeCloseTo(29.23, 0);
  });

  it("flags picks that look like the price colors", () => {
    expect(priceColorClash("#dc2626")).toBe("red");
    expect(priceColorClash("#16a34a")).toBe("green");
    expect(priceColorClash("#2563eb")).toBeNull();
    expect(priceColorClash("#7c3aed")).toBeNull();
    // Greys have no hue to confuse.
    expect(priceColorClash("#6b6b6b")).toBeNull();
  });
});
