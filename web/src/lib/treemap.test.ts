import { describe, expect, it } from "vitest";

import { squarify } from "./treemap";

const rect = { x: 0, y: 0, w: 600, h: 400 };

describe("squarify", () => {
  it("gives each tile an area proportional to its value and covers the rectangle", () => {
    const values = [6, 6, 4, 3, 2, 2, 1];
    const tiles = squarify(values, (v) => v, rect);
    const total = values.reduce((a, b) => a + b, 0);
    expect(tiles).toHaveLength(values.length);
    for (const t of tiles) {
      expect(t.w * t.h).toBeCloseTo((t.item / total) * rect.w * rect.h, 6);
      expect(t.x).toBeGreaterThanOrEqual(0);
      expect(t.y).toBeGreaterThanOrEqual(0);
      expect(t.x + t.w).toBeLessThanOrEqual(rect.w + 1e-9);
      expect(t.y + t.h).toBeLessThanOrEqual(rect.h + 1e-9);
    }
    const area = tiles.reduce((a, t) => a + t.w * t.h, 0);
    expect(area).toBeCloseTo(rect.w * rect.h, 6);
  });

  it("keeps tiles close to square (the paper's example stays under 3:1)", () => {
    const tiles = squarify([6, 6, 4, 3, 2, 2, 1], (v) => v, {
      x: 0,
      y: 0,
      w: 6,
      h: 4,
    });
    for (const t of tiles) expect(Math.max(t.w / t.h, t.h / t.w)).toBeLessThan(3);
  });

  it("orders largest first and drops non-positive values", () => {
    const tiles = squarify([1, 0, -2, 5, Number.NaN], (v) => v, rect);
    expect(tiles.map((t) => t.item)).toEqual([5, 1]);
    expect(squarify([], (v: number) => v, rect)).toEqual([]);
    expect(squarify([1], (v) => v, rect)).toEqual([{ item: 1, ...rect }]);
  });
});
