import { describe, expect, it } from "vitest";

import {
  adjustedChange,
  groupReturn,
  type HeatmapStock,
  heatBucket,
  heatColor,
  industryGroups,
  themeGroups,
  UNCLASSIFIED,
} from "./heatmap-data";

const stock = (
  id: number,
  marketCap: number,
  change: number | null,
  industry: string | null = "半導體業",
): HeatmapStock => ({ id, symbol: String(id), name: `S${id}`, industry, marketCap, change });

describe("adjustedChange", () => {
  it("compares closes on one share basis", () => {
    expect(adjustedChange(110, 1, 100, 1)).toBeCloseTo(0.1);
    // Ex-dividend: base 100 restated by its factor 0.95 -> 95, latest 95 -> flat.
    expect(adjustedChange(95, 1, 100, 0.95)).toBeCloseTo(0);
    expect(adjustedChange(95, 1, null, null)).toBeNull();
    expect(adjustedChange(95, 1, 0, 1)).toBeNull();
  });
});

describe("groupReturn", () => {
  it("is the buy-and-hold return weighted by value at the base date", () => {
    // A: 100 -> 110 (cap now 110); B: 100 -> 90 (cap now 90). Held equally: flat.
    expect(groupReturn([stock(1, 110, 0.1), stock(2, 90, -0.1)])).toBeCloseTo(0);
    expect(groupReturn([stock(1, 110, 0.1), stock(2, 50, null)])).toBeCloseTo(0.1);
    expect(groupReturn([stock(1, 50, null)])).toBeNull();
  });
});

describe("groups", () => {
  it("groups by industry, unclassified included, largest first with members by size", () => {
    const groups = industryGroups([
      stock(1, 10, 0.01),
      stock(2, 30, 0.02),
      stock(3, 100, 0, "金融保險業"),
      stock(4, 5, 0, null),
    ]);
    expect(groups.map((g) => g.name)).toEqual(["金融保險業", "半導體業", UNCLASSIFIED]);
    expect(groups[1].members.map((m) => m.id)).toEqual([2, 1]);
    expect(groups[1].marketCap).toBe(40);
  });

  it("puts a stock in every theme it belongs to and skips unknown stocks", () => {
    const groups = themeGroups(
      [stock(1, 10, 0.01), stock(2, 30, 0.02)],
      [
        { themeId: 7, themeName: "AI", stockId: 1 },
        { themeId: 7, themeName: "AI", stockId: 2 },
        { themeId: 8, themeName: "CoWoS", stockId: 2 },
        { themeId: 8, themeName: "CoWoS", stockId: 99 },
      ],
    );
    expect(groups.map((g) => [g.key, g.name, g.members.length])).toEqual([
      ["7", "AI", 2],
      ["8", "CoWoS", 1],
    ]);
  });
});

describe("heatBucket", () => {
  it("uses equal steps per arm, scaled by the square root of the period", () => {
    expect(heatBucket(0.001, 1)).toBe(0);
    expect(heatBucket(0.005, 1)).toBe(1);
    expect(heatBucket(-0.015, 1)).toBe(-2);
    expect(heatBucket(0.099, 1)).toBe(3);
    expect(heatBucket(0.015, 20)).toBe(1); // 1.5% over a month is a light tile
    expect(heatBucket(null, 1)).toBe(0);
  });

  it("maps buckets to the up/down tokens around the neutral surface", () => {
    expect(heatColor(0)).toBe("var(--muted)");
    expect(heatColor(3)).toBe("color-mix(in oklab, var(--price-up) 100%, var(--muted))");
    expect(heatColor(-1)).toBe("color-mix(in oklab, var(--price-down) 35%, var(--muted))");
  });
});
