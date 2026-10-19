import { describe, expect, it } from "vitest";

import { moveSymbol, sortWatchlist } from "./watchlist-sort";

const items = [
  { symbol: "2330", position: 2, addedAt: "2026-10-01", price: 1450, changePercent: 1.2 },
  { symbol: "0050", position: 1, addedAt: "2026-10-03", price: 190, changePercent: null },
  { symbol: "2317", position: 3, addedAt: "2026-10-02", price: null, changePercent: -0.5 },
];
const symbols = (xs: { symbol: string }[]) => xs.map((x) => x.symbol);

describe("sortWatchlist", () => {
  it("sorts by each key, missing values last either way", () => {
    expect(symbols(sortWatchlist(items, "custom", false))).toEqual(["0050", "2330", "2317"]);
    expect(symbols(sortWatchlist(items, "symbol", true))).toEqual(["2330", "2317", "0050"]);
    expect(symbols(sortWatchlist(items, "change", true))).toEqual(["2330", "2317", "0050"]);
    expect(symbols(sortWatchlist(items, "change", false))).toEqual(["2317", "2330", "0050"]);
    expect(symbols(sortWatchlist(items, "price", false))).toEqual(["0050", "2330", "2317"]);
    expect(symbols(sortWatchlist(items, "added", true))).toEqual(["0050", "2317", "2330"]);
  });
});

describe("moveSymbol", () => {
  it("swaps with the neighbour and stops at the ends", () => {
    expect(moveSymbol(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(moveSymbol(["a", "b", "c"], "c", 1)).toEqual(["a", "b", "c"]);
  });
});
