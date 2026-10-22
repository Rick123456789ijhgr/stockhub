/**
 * The site shows financial data for a fixed number of calendar years: this year and the
 * four before it. On January 1 the window moves on and the oldest year drops out. Display
 * only: the database keeps the full history (2013 on) for M7 backtests (D-114).
 */

export const FINANCIAL_YEARS = 5;

/** First date shown: January 1 of the oldest year in the window (today is YYYY-MM-DD). */
export function financialWindowStart(today: string, years: number = FINANCIAL_YEARS): string {
  return `${Number(today.slice(0, 4)) - years + 1}-01-01`;
}

/** Rows dated on or after the window start. */
export function inFinancialWindow<T>(rows: readonly T[], date: (row: T) => string, today: string): T[] {
  const start = financialWindowStart(today);
  return rows.filter((row) => date(row) >= start);
}
