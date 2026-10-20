/**
 * Valuation series, percentiles and river-chart bands (twin of py/stockhub/engine/valuation.py;
 * change both together and regenerate testdata/valuation.json with
 * py/scripts/gen_valuation_fixture.py).
 *
 * Raw closes; each day uses the latest quarter available by then (publish date, else the
 * statutory deadline). P/E needs a positive TTM EPS, P/B a positive book value. Trailing
 * yield = cash dividends with an ex-date in the 365 days up to the day / close. Percentile =
 * (below + half equal) / count. River multiples: evenly spaced from the 5th to the 95th
 * percentile. Dates are ISO strings.
 */

export type Metric = "pe" | "pb" | "dividendYield";

export type PricePoint = { date: string; close: number };
export type QuarterPoint = {
  periodEnd: string;
  availableDate: string;
  epsTtm: number | null;
  bvps: number | null;
};
export type Dividend = { exDate: string; cash: number };

export type ValuationPoint = {
  date: string;
  close: number;
  epsTtm: number | null;
  bvps: number | null;
  pe: number | null;
  pb: number | null;
  dividendTtm: number;
  dividendYield: number | null;
};

export const BAND_QUANTILES = [0.05, 0.95] as const;
export const BAND_COUNT = 5;

export function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Same month and day `years` earlier/later; Feb 29 falls back to Feb 28. */
export function shiftYears(iso: string, years: number): string {
  const year = Number(iso.slice(0, 4)) + years;
  let rest = iso.slice(4);
  if (rest === "-02-29") rest = "-02-28";
  return `${String(year).padStart(4, "0")}${rest}`;
}

const byKey = <T>(key: (x: T) => string) => (a: T, b: T) =>
  key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0;

/** Price over trailing-four-quarter EPS; none for losses (EPS not positive). */
export function peRatio(close: number, epsTtm: number | null): number | null {
  return epsTtm !== null && epsTtm > 0 && close > 0 ? close / epsTtm : null;
}

/** Price over book value per share; none when book value is not positive. */
export function pbRatio(close: number, bvps: number | null): number | null {
  return bvps !== null && bvps > 0 && close > 0 ? close / bvps : null;
}

export function valuationSeries(
  prices: PricePoint[],
  quarters: QuarterPoint[],
  dividends: Dividend[],
): ValuationPoint[] {
  const byAvailable = [...quarters].sort(byKey((q) => `${q.availableDate}|${q.periodEnd}`));
  const divs = [...dividends].sort(byKey((d) => d.exDate));
  const out: ValuationPoint[] = [];
  let current: QuarterPoint | null = null;
  let nextQ = 0;
  for (const p of [...prices].sort(byKey((x) => x.date))) {
    while (nextQ < byAvailable.length && byAvailable[nextQ].availableDate <= p.date) {
      const candidate = byAvailable[nextQ];
      if (current === null || candidate.periodEnd >= current.periodEnd) current = candidate;
      nextQ += 1;
    }
    const start = shiftDays(p.date, -365);
    let dividend = 0;
    for (const d of divs) if (start < d.exDate && d.exDate <= p.date) dividend += d.cash;
    const eps = current ? current.epsTtm : null;
    const bvps = current ? current.bvps : null;
    out.push({
      date: p.date,
      close: p.close,
      epsTtm: eps,
      bvps,
      pe: peRatio(p.close, eps),
      pb: pbRatio(p.close, bvps),
      dividendTtm: dividend,
      dividendYield: p.close > 0 ? dividend / p.close : null,
    });
  }
  return out;
}

/** Points from `years` before the last point's date through the last point. */
export function windowYears(points: ValuationPoint[], years: number): ValuationPoint[] {
  if (points.length === 0) return [];
  const start = shiftYears(points[points.length - 1].date, -years);
  return points.filter((p) => p.date >= start);
}

export function metricValues(points: ValuationPoint[], metric: Metric): number[] {
  const out: number[] = [];
  for (const p of points) {
    const v = p[metric];
    if (v !== null) out.push(v);
  }
  return out;
}

export function percentileRank(values: number[], current: number): number | null {
  if (values.length === 0) return null;
  let below = 0;
  let equal = 0;
  for (const v of values) {
    if (v < current) below += 1;
    else if (v === current) equal += 1;
  }
  return (below + 0.5 * equal) / values.length;
}

export function quantile(values: number[], q: number): number | null {
  if (values.length === 0) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const pos = q * (ordered.length - 1);
  const lower = Math.trunc(pos);
  const upper = Math.min(lower + 1, ordered.length - 1);
  return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower);
}

export type MetricSummary = {
  current: number | null;
  percentile: number | null;
  low: number | null;
  median: number | null;
  high: number | null;
  count: number;
};

export function summarize(points: ValuationPoint[], metric: Metric, years: number): MetricSummary {
  const values = metricValues(windowYears(points, years), metric);
  const current = points.length > 0 ? points[points.length - 1][metric] : null;
  let low: number | null = null;
  let high: number | null = null;
  for (const v of values) {
    if (low === null || v < low) low = v;
    if (high === null || v > high) high = v;
  }
  return {
    current,
    percentile: current !== null ? percentileRank(values, current) : null,
    low,
    median: quantile(values, 0.5),
    high,
    count: values.length,
  };
}

/** `count` multiples evenly spaced between the 5th and 95th percentile. */
export function bandMultiples(values: number[], count: number = BAND_COUNT): number[] {
  const low = quantile(values, BAND_QUANTILES[0]);
  const high = quantile(values, BAND_QUANTILES[1]);
  if (low === null || high === null) return [];
  if (count === 1 || high === low) return [low];
  const step = (high - low) / (count - 1);
  return Array.from({ length: count }, (_, i) => low + step * i);
}

/** Per point, the price at each multiple (null while the base is not positive). */
export function riverBands(
  points: ValuationPoint[],
  metric: "pe" | "pb",
  multiples: number[],
): (number | null)[][] {
  return points.map((p) => {
    const base = metric === "pe" ? p.epsTtm : p.bvps;
    return multiples.map((m) => (base !== null && base > 0 ? base * m : null));
  });
}
