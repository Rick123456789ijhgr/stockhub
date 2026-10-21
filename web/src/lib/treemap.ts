/**
 * Squarified treemap layout (Bruls, Huizing, van Wijk 2000): tiles with areas proportional
 * to their values and aspect ratios close to 1. Pure; the heatmap renders the rectangles.
 */

export type Rect = { x: number; y: number; w: number; h: number };
export type Tile<T> = Rect & { item: T };

/** Worst aspect ratio of a row of areas laid along a side of length `side`. */
function worst(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  return Math.max((s2 * max) / (sum * sum), (sum * sum) / (s2 * min));
}

/**
 * Lay out `items` (with value > 0; others are dropped) inside `rect`, largest first.
 * The returned tiles exactly cover the rectangle.
 */
export function squarify<T>(items: readonly T[], value: (item: T) => number, rect: Rect): Tile<T>[] {
  const entries = items
    .map((item) => ({ item, v: value(item) }))
    .filter((e) => e.v > 0 && Number.isFinite(e.v))
    .sort((a, b) => b.v - a.v);
  const total = entries.reduce((a, e) => a + e.v, 0);
  if (!entries.length || rect.w <= 0 || rect.h <= 0) return [];
  const scale = (rect.w * rect.h) / total;
  const areas = entries.map((e) => e.v * scale);

  const out: Tile<T>[] = [];
  let free = { ...rect };
  let start = 0;
  while (start < entries.length) {
    const side = Math.min(free.w, free.h);
    let end = start + 1;
    while (
      end < entries.length &&
      worst(areas.slice(start, end + 1), side) <= worst(areas.slice(start, end), side)
    ) {
      end += 1;
    }
    const rowArea = areas.slice(start, end).reduce((a, b) => a + b, 0);
    const last = end === entries.length;
    if (free.w >= free.h) {
      // Column along the left edge.
      const width = last ? free.w : rowArea / free.h;
      let y = free.y;
      for (let i = start; i < end; i++) {
        const h = i === end - 1 ? free.y + free.h - y : areas[i] / width;
        out.push({ item: entries[i].item, x: free.x, y, w: width, h });
        y += h;
      }
      free = { x: free.x + width, y: free.y, w: free.w - width, h: free.h };
    } else {
      // Row along the top edge.
      const height = last ? free.h : rowArea / free.w;
      let x = free.x;
      for (let i = start; i < end; i++) {
        const w = i === end - 1 ? free.x + free.w - x : areas[i] / height;
        out.push({ item: entries[i].item, x, y: free.y, w, h: height });
        x += w;
      }
      free = { x: free.x, y: free.y + height, w: free.w, h: free.h - height };
    }
    start = end;
  }
  return out;
}
