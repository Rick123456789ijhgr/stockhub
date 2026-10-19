/** Intraday quote shape and Taipei session timing (safe for client components). */

export type LiveQuote = {
  tradeDate: string;
  /** ISO timestamp (UTC) of the last trade. */
  quoteTime: string;
  price: string | null;
  open: string | null;
  high: string | null;
  low: string | null;
  prevClose: string | null;
  /** Cumulative regular-session shares. */
  volume: string;
  bid: string | null;
  ask: string | null;
};

const TAIPEI_PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/**
 * Whether the regular session (09:00 to 13:30, plus five minutes for the closing auction to
 * land) is running in Taipei. Weekday-only: holidays merely cause a few idle refetches.
 */
export function isSessionOpen(now: Date): boolean {
  const part = Object.fromEntries(TAIPEI_PARTS.formatToParts(now).map((p) => [p.type, p.value]));
  if (part.weekday === "Sat" || part.weekday === "Sun") return false;
  const minutes = Number(part.hour) * 60 + Number(part.minute);
  return minutes >= 9 * 60 && minutes <= 13 * 60 + 35;
}

/** A quote is worth showing when it is newer than the latest daily bar (i.e. today, intraday). */
export function isFresherThanDaily(quote: LiveQuote | null, latestBarDate: string | null): boolean {
  if (!quote || quote.price === null) return false;
  return latestBarDate === null || quote.tradeDate > latestBarDate;
}

const TAIPEI_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei" });

/** Today's date in Taipei as "YYYY-MM-DD". */
export function taipeiToday(now: Date = new Date()): string {
  return TAIPEI_DATE.format(now);
}
