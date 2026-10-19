/** Chart data shapes and pure transforms (safe for client components). */

/** [trade date, open, high, low, close, volume (shares), adj_factor]; traded bars only. */
export type ChartBar = [string, number, number, number, number, number, number];

export type PriceMode = "adjusted" | "raw";

export type Ohlc = { time: string; open: number; high: number; low: number; close: number };

/** Prices to draw: raw, or multiplied by adj_factor (還原價, today's share basis). */
export function toOhlc(bars: readonly ChartBar[], mode: PriceMode): Ohlc[] {
  return bars.map(([time, o, h, l, c, , f]) => {
    const k = mode === "adjusted" ? f : 1;
    return { time, open: o * k, high: h * k, low: l * k, close: c * k };
  });
}

export const RANGES = [
  { key: "6M", label: "6 個月", months: 6 },
  { key: "1Y", label: "1 年", months: 12 },
  { key: "3Y", label: "3 年", months: 36 },
  { key: "5Y", label: "5 年", months: 60 },
  { key: "ALL", label: "全部", months: null },
] as const;

export type RangeKey = (typeof RANGES)[number]["key"];

/** Months the first chart request covers ("recent"): 3 years plus a half-year warm-up. */
export const RECENT_RANGE_MONTHS = 36;

/** Whether `range` shows more than the recent load, so the full history must be fetched. */
export function needsFullHistory(range: RangeKey): boolean {
  const months = RANGES.find((r) => r.key === range)?.months ?? null;
  return months === null || months > RECENT_RANGE_MONTHS;
}

/** Index of the first bar inside `range`, counted back from the latest bar. */
export function rangeStartIndex(bars: readonly ChartBar[], range: RangeKey): number {
  const months = RANGES.find((r) => r.key === range)?.months ?? null;
  if (months === null || bars.length === 0) return 0;
  const last = new Date(`${bars[bars.length - 1][0]}T00:00:00Z`);
  last.setUTCMonth(last.getUTCMonth() - months);
  const cutoff = last.toISOString().slice(0, 10);
  const index = bars.findIndex(([time]) => time > cutoff);
  return index < 0 ? 0 : index;
}

/** Close-to-close change in percent on the adjusted basis; null for the first bar. */
export function adjustedChangePercent(bars: readonly ChartBar[], index: number): number | null {
  if (index <= 0 || index >= bars.length) return null;
  const [, , , , close, , factor] = bars[index];
  const [, , , , prevClose, , prevFactor] = bars[index - 1];
  const prev = prevClose * prevFactor;
  return prev === 0 ? null : ((close * factor) / prev - 1) * 100;
}
