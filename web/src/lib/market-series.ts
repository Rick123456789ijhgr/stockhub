/** Market and macro series helpers (pure): latest change, year-over-year, spreads. */

export type SeriesPoint = { date: string; value: number };

export type SeriesCategory = "tw_index" | "intl_index" | "fx" | "rate" | "commodity" | "volatility" | "macro";

export type SeriesInfo = {
  code: string;
  name: string;
  category: SeriesCategory;
  unit: string;
  frequency: "daily" | "monthly";
};

export type SeriesLatest = {
  date: string;
  value: number;
  label: string | null;
  /** Change against the previous observation: fraction for prices, points for rates. */
  change: number | null;
  prevDate: string | null;
};

/** Categories whose moves read as market up/down (red/green); rates and macro stay neutral. */
export const PRICE_LIKE: ReadonlySet<SeriesCategory> = new Set(["tw_index", "intl_index", "commodity"]);

/** Rates and percentages change in points, everything else as a fraction of the last value. */
export function changesInPoints(info: Pick<SeriesInfo, "unit">): boolean {
  return info.unit === "percent" || info.unit === "score";
}

export function latestChange(
  points: readonly (SeriesPoint & { label?: string | null })[],
  inPoints: boolean,
): SeriesLatest | null {
  const last = points.at(-1);
  if (!last) return null;
  const prev = points.at(-2);
  let change: number | null = null;
  if (prev) change = inPoints ? last.value - prev.value : prev.value > 0 ? last.value / prev.value - 1 : null;
  return {
    date: last.date,
    value: last.value,
    label: last.label ?? null,
    change,
    prevDate: prev?.date ?? null,
  };
}

/** Year-over-year change of a monthly index (e.g. CPI), as a fraction, by calendar month. */
export function yearOverYear(points: readonly SeriesPoint[]): SeriesPoint[] {
  const byDate = new Map(points.map((p) => [p.date, p.value]));
  const out: SeriesPoint[] = [];
  for (const p of points) {
    const [y, m, d] = p.date.split("-");
    const base = byDate.get(`${Number(y) - 1}-${m}-${d}`);
    if (base && base > 0) out.push({ date: p.date, value: p.value / base - 1 });
  }
  return out;
}

/** a − b on the dates both series have (e.g. 10-year minus 2-year yield). */
export function spread(a: readonly SeriesPoint[], b: readonly SeriesPoint[]): SeriesPoint[] {
  const other = new Map(b.map((p) => [p.date, p.value]));
  return a.flatMap((p) => {
    const v = other.get(p.date);
    return v === undefined ? [] : [{ date: p.date, value: p.value - v }];
  });
}

/** Percent numbers (5.24) as fractions (0.0524) for the shared "percent" chart format. */
export function percentToFraction(points: readonly SeriesPoint[]): SeriesPoint[] {
  return points.map((p) => ({ date: p.date, value: p.value / 100 }));
}

export function formatSeriesValue(value: number, unit: string): string {
  if (unit === "percent") return `${value.toFixed(2)}%`;
  if (unit === "score") return `${value.toFixed(0)} 分`;
  const digits = unit === "TWD" ? 3 : value >= 1000 ? 0 : 2;
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
