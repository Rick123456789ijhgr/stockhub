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

/** Minutes after Taipei midnight, and whether it is a weekend there. */
function taipeiClock(now: Date): { minutes: number; weekend: boolean } {
  const part = Object.fromEntries(TAIPEI_PARTS.formatToParts(now).map((p) => [p.type, p.value]));
  return {
    minutes: Number(part.hour) * 60 + Number(part.minute),
    weekend: part.weekday === "Sat" || part.weekday === "Sun",
  };
}

export type SessionPhase = "holiday" | "pre" | "trial" | "continuous" | "closingAuction" | "closed";

/** The rail spans the trial match to the close: 08:30 to 13:30 Taipei (D-126). */
export const RAIL_START = 8 * 60 + 30;
export const RAIL_END = 13 * 60 + 30;
export const OPEN_AT = 9 * 60;
export const CLOSING_AUCTION_AT = 13 * 60 + 25;

export const PHASE_LABEL: Record<SessionPhase, string> = {
  holiday: "休市",
  pre: "盤前",
  trial: "試撮",
  continuous: "盤中",
  closingAuction: "收盤集合競價",
  closed: "已收盤",
};

/**
 * Where the Taiwan session stands at `now`: its phase and the position on the 08:30–13:30
 * rail (0..1). `tradingDay` comes from the trading calendar for `date`; when the clock has
 * moved past that date (a page left open overnight) weekends count as holidays.
 */
export function sessionPhase(
  now: Date,
  day: { date: string; tradingDay: boolean | null },
): { phase: SessionPhase; progress: number } {
  const { minutes, weekend } = taipeiClock(now);
  const trading = taipeiToday(now) === day.date && day.tradingDay !== null ? day.tradingDay : !weekend;
  const progress = Math.min(1, Math.max(0, (minutes - RAIL_START) / (RAIL_END - RAIL_START)));
  if (!trading) return { phase: "holiday", progress: 0 };
  if (minutes < RAIL_START) return { phase: "pre", progress };
  if (minutes < OPEN_AT) return { phase: "trial", progress };
  if (minutes < CLOSING_AUCTION_AT) return { phase: "continuous", progress };
  if (minutes < RAIL_END) return { phase: "closingAuction", progress };
  return { phase: "closed", progress };
}
