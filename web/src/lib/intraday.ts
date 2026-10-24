/** The day's intraday samples (quotes_intraday, one per 30 s round) and their chart form; client-safe. */

export type IntradayPoint = {
  /** ISO timestamp (UTC) the round took the sample. */
  at: string;
  price: string;
};

export type IntradayDay = {
  tradeDate: string;
  /** Reference price the day's change is measured against; null when unknown. */
  prevClose: string | null;
  points: IntradayPoint[];
};

const TAIPEI_OFFSET_SECONDS = 8 * 3600;

/**
 * Chart time for a sample. lightweight-charts prints timestamps as UTC, so shifting by the
 * fixed +8 h (Taiwan has no daylight saving) makes the axis read Taipei time.
 */
export function chartSeconds(iso: string): number {
  return Math.floor(Date.parse(iso) / 1000) + TAIPEI_OFFSET_SECONDS;
}

/** "HH:MM:SS" in Taipei for a chart time from `chartSeconds`. */
export function chartClock(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(11, 19);
}

/** Line data in time order, one point per distinct second. */
export function intradayLine(day: IntradayDay): { time: number; value: number }[] {
  const byTime = new Map<number, number>();
  for (const p of day.points) byTime.set(chartSeconds(p.at), Number(p.price));
  return [...byTime].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }));
}

/**
 * Fill a missing reference price from the daily bar of the same day (its rebased previous
 * close, as the quote header shows it); quotes_latest only has it while that day is current.
 */
export function withDailyReference(
  day: IntradayDay,
  bar: { tradeDate: string; prevClose: string | null } | undefined,
): IntradayDay {
  if (day.prevClose !== null || !bar || bar.tradeDate !== day.tradeDate) return day;
  return { ...day, prevClose: bar.prevClose };
}

/** The level the chart splits up and down colors at: the reference price, else the first sample. */
export function intradayBase(day: IntradayDay): number | null {
  if (day.prevClose !== null) return Number(day.prevClose);
  return day.points.length > 0 ? Number(day.points[0].price) : null;
}

/**
 * Show the chart for the latest sampled day unless a newer daily bar exists (then the
 * samples belong to an older session than the quote header shows).
 */
export function showIntraday(day: IntradayDay | null, latestBarDate: string | null): day is IntradayDay {
  if (!day || day.points.length === 0) return false;
  return latestBarDate === null || day.tradeDate >= latestBarDate;
}
