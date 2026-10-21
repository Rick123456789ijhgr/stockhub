/**
 * Heatmap numbers (pure): per-stock change over a period, market-cap-weighted group returns,
 * and the diverging colour bucket. Server code (lib/heatmap.ts) loads the rows.
 */

export const HEATMAP_PERIODS = { "1d": 1, "5d": 5, "20d": 20 } as const;
export type HeatmapPeriod = keyof typeof HEATMAP_PERIODS;

export type HeatmapStock = {
  id: number;
  symbol: string;
  name: string;
  industry: string | null;
  /** Close × issued shares on the latest date, TWD. */
  marketCap: number;
  /** Fractional change over the period on adjusted prices; null without a base close. */
  change: number | null;
};

export type HeatmapGroup = {
  key: string;
  name: string;
  marketCap: number;
  /** Buy-and-hold return of the group's members (cap-weighted at the base date). */
  change: number | null;
  members: HeatmapStock[];
};

/**
 * Change from a base close to the latest close, both restated on one share basis
 * (same as `rebasedPrevClose`: price × adj_factor).
 */
export function adjustedChange(
  close: number,
  factor: number,
  baseClose: number | null,
  baseFactor: number | null,
): number | null {
  if (baseClose === null || baseFactor === null || baseClose <= 0 || baseFactor <= 0) return null;
  return (close * factor) / (baseClose * baseFactor) - 1;
}

/**
 * Group return = Σ cap now / Σ cap at base − 1, with cap at base = cap now / (1 + change):
 * what holding every member in proportion to its value at the base date returned.
 */
export function groupReturn(members: readonly HeatmapStock[]): number | null {
  let now = 0;
  let base = 0;
  for (const m of members) {
    if (m.change === null || m.marketCap <= 0) continue;
    now += m.marketCap;
    base += m.marketCap / (1 + m.change);
  }
  return base > 0 ? now / base - 1 : null;
}

function toGroup(key: string, name: string, members: HeatmapStock[]): HeatmapGroup {
  const sorted = [...members].sort((a, b) => b.marketCap - a.marketCap);
  return {
    key,
    name,
    marketCap: sorted.reduce((a, m) => a + m.marketCap, 0),
    change: groupReturn(sorted),
    members: sorted,
  };
}

export const UNCLASSIFIED = "未分類";

/** Stocks grouped by exchange industry, largest group first. */
export function industryGroups(stocks: readonly HeatmapStock[]): HeatmapGroup[] {
  const by = new Map<string, HeatmapStock[]>();
  for (const s of stocks) {
    const name = s.industry ?? UNCLASSIFIED;
    by.set(name, [...(by.get(name) ?? []), s]);
  }
  return [...by.entries()]
    .map(([name, members]) => toGroup(name, name, members))
    .sort((a, b) => b.marketCap - a.marketCap);
}

/** Stocks grouped by theme (a stock may sit in several), largest group first. */
export function themeGroups(
  stocks: readonly HeatmapStock[],
  memberships: readonly {
    themeId: number;
    themeName: string;
    stockId: number;
  }[],
): HeatmapGroup[] {
  const byId = new Map(stocks.map((s) => [s.id, s]));
  const by = new Map<number, { name: string; members: HeatmapStock[] }>();
  for (const m of memberships) {
    const stock = byId.get(m.stockId);
    if (!stock) continue;
    const entry = by.get(m.themeId) ?? { name: m.themeName, members: [] };
    entry.members.push(stock);
    by.set(m.themeId, entry);
  }
  return [...by.entries()]
    .map(([id, { name, members }]) => toGroup(String(id), name, members))
    .sort((a, b) => b.marketCap - a.marketCap);
}

/**
 * Diverging bucket, −3 … 3 (0 = flat). Thresholds grow with √days so a 20-day map is not
 * saturated by moves that are ordinary over a month: 1 day = 0.25% / 1% / 2.5%.
 */
export function heatBucket(change: number | null, days: number): number {
  if (change === null || !Number.isFinite(change)) return 0;
  const unit = 0.01 * Math.sqrt(days);
  const size = Math.abs(change);
  const step = size < 0.25 * unit ? 0 : size < unit ? 1 : size < 2.5 * unit ? 2 : 3;
  return Math.sign(change) * step;
}

const MIX = [0, 35, 65, 100];

/** CSS colour of a bucket: the up/down token mixed into the neutral muted surface. */
export function heatColor(bucket: number): string {
  if (bucket === 0) return "var(--muted)";
  const token = bucket > 0 ? "var(--price-up)" : "var(--price-down)";
  return `color-mix(in oklab, ${token} ${MIX[Math.abs(bucket)]}%, var(--muted))`;
}
