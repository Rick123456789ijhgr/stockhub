/**
 * Pure helpers for the data-coverage views on /status (no DB access, unit-tested).
 *
 * Cell states:
 *   full        both markets have bars
 *   partial     only one market has bars
 *   gap         a past trading day inside the fetched range with no bars (needs attention)
 *   notFetched  a past trading day outside the fetched range (backfill not run yet)
 *   closed      holiday or weekend
 *   future      today or later without data
 */

export type DayCoverage = {
  date: string; // YYYY-MM-DD (Taipei trading date)
  isTradingDay: boolean;
  twse: number;
  tpex: number;
};

export type CellState = "full" | "partial" | "gap" | "notFetched" | "closed" | "future";

export type Cell = { day: DayCoverage; state: CellState };

export type FetchedRange = { first: string; last: string } | null;

/** Date windows a running backfill has yet to reach: missing data there is not a gap. */
export type Pending = { from: string; to: string }[];

export function fetchedRange(days: DayCoverage[]): FetchedRange {
  let first: string | null = null;
  let last: string | null = null;
  for (const d of days) {
    if (d.twse + d.tpex === 0) continue;
    if (first === null || d.date < first) first = d.date;
    if (last === null || d.date > last) last = d.date;
  }
  return first && last ? { first, last } : null;
}

export function cellState(
  day: DayCoverage,
  today: string,
  range: FetchedRange,
  pending: Pending = [],
): CellState {
  if (day.twse > 0 && day.tpex > 0) return "full";
  if (day.twse > 0 || day.tpex > 0) return "partial";
  if (day.date >= today) return "future";
  if (!day.isTradingDay) return "closed";
  const queued = pending.some((p) => day.date >= p.from && day.date <= p.to);
  if (!queued && range && day.date >= range.first && day.date <= range.last) return "gap";
  return "notFetched";
}

export type MonthRow = { month: number; cells: (Cell | null)[] };

/** 12 rows (months) × 31 columns (day of month); null where the date does not exist. */
export function yearGrid(
  year: number,
  days: DayCoverage[],
  today: string,
  range: FetchedRange,
  pending: Pending = [],
): MonthRow[] {
  const byDate = new Map(days.map((d) => [d.date, d]));
  return Array.from({ length: 12 }, (_, m) => {
    const cells: (Cell | null)[] = [];
    for (let dom = 1; dom <= 31; dom++) {
      const date = isoDate(year, m + 1, dom);
      if (date === null) {
        cells.push(null);
        continue;
      }
      const day = byDate.get(date) ?? { date, isTradingDay: false, twse: 0, tpex: 0 };
      cells.push({ day, state: cellState(day, today, range, pending) });
    }
    return { month: m + 1, cells };
  });
}

export type YearSummary = {
  year: number;
  tradingDays: number; // past trading days per calendar (plus any day with data)
  fetched: number; // of those, days with bars in both markets
  partial: number;
  gaps: number;
};

export function summarizeYears(
  days: DayCoverage[],
  today: string,
  pending: Pending = [],
): YearSummary[] {
  const range = fetchedRange(days);
  const years = new Map<number, YearSummary>();
  for (const day of days) {
    const year = Number(day.date.slice(0, 4));
    const summary = years.get(year) ?? { year, tradingDays: 0, fetched: 0, partial: 0, gaps: 0 };
    const state = cellState(day, today, range, pending);
    if (state === "full" || state === "partial" || state === "gap" || state === "notFetched") {
      summary.tradingDays += 1;
    }
    if (state === "full") summary.fetched += 1;
    if (state === "partial") summary.partial += 1;
    if (state === "gap") summary.gaps += 1;
    years.set(year, summary);
  }
  return [...years.values()].sort((a, b) => b.year - a.year);
}

export function gapDays(
  days: DayCoverage[],
  today: string,
  pending: Pending = [],
): DayCoverage[] {
  const range = fetchedRange(days);
  return days.filter((d) => {
    const state = cellState(d, today, range, pending);
    return state === "gap" || state === "partial";
  });
}

function isoDate(year: number, month: number, day: number): string | null {
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCMonth() !== month - 1) return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Progress of a running backfill: share of its trading days already processed. */
export function backfillProgress(
  tradingDays: string[],
  nextDate: string | null,
  startedAt: string,
  now: Date,
): { done: number; total: number; percent: number; etaSeconds: number | null } {
  const total = tradingDays.length;
  const done = nextDate ? tradingDays.filter((d) => d < nextDate).length : 0;
  const percent = total === 0 ? 0 : (done / total) * 100;
  const elapsed = (now.getTime() - new Date(startedAt).getTime()) / 1000;
  const etaSeconds = done > 0 && done < total ? Math.round((elapsed / done) * (total - done)) : null;
  return { done, total, percent, etaSeconds };
}
