/** Watchlist sorting (safe for client components). */

export const SORT_KEYS = ["custom", "symbol", "change", "price", "added"] as const;
export type SortKey = (typeof SORT_KEYS)[number];

export const SORT_LABEL: Record<SortKey, string> = {
  custom: "自訂順序",
  symbol: "代號",
  change: "漲跌幅",
  price: "價格",
  added: "加入時間",
};

export type Sortable = {
  symbol: string;
  position: number;
  addedAt: string;
  price: number | null;
  changePercent: number | null;
};

/** Sorted copy; rows without a value go last in either direction, ties by custom order. */
export function sortWatchlist<T extends Sortable>(items: readonly T[], key: SortKey, desc: boolean): T[] {
  const value = (t: T): number | string | null => {
    switch (key) {
      case "custom":
        return t.position;
      case "symbol":
        return t.symbol;
      case "change":
        return t.changePercent;
      case "price":
        return t.price;
      case "added":
        return t.addedAt;
    }
  };
  return [...items].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va === null || vb === null) {
      if (va !== vb) return va === null ? 1 : -1;
    } else if (va !== vb) {
      const cmp = va < vb ? -1 : 1;
      return desc ? -cmp : cmp;
    }
    return a.position - b.position;
  });
}

/** Move one symbol up or down within the custom order; the full new order. */
export function moveSymbol(order: readonly string[], symbol: string, delta: -1 | 1): string[] {
  const i = order.indexOf(symbol);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= order.length) return [...order];
  const next = [...order];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}
