import "server-only";

import type { Kysely } from "kysely";

import type { DB } from "@/lib/db";
import { recentTradingDates } from "@/lib/stocks";

export type SessionStatus = {
  /** Taipei date the calendar answer is for. */
  date: string;
  /** From trading_calendar; null when the calendar has no row for `date`. */
  tradingDay: boolean | null;
  nextTradingDay: string | null;
  /** Latest intraday quote written today (ISO), if any. */
  lastQuoteAt: string | null;
  /** Latest trading day with the market's closes in. */
  lastCloseDate: string | null;
};

/** What the session rail (D-126) needs: today's calendar, the next session and data freshness. */
export async function getSessionStatus(db: Kysely<DB>, today: string): Promise<SessionStatus> {
  const [calendar, quote, closes] = await Promise.all([
    db
      .selectFrom("trading_calendar")
      .select(["date", "is_trading_day as tradingDay"])
      .where("date", ">=", today)
      .orderBy("date")
      .limit(15)
      .execute(),
    db
      .selectFrom("quotes_latest")
      .select((eb) => eb.fn.max("quote_time").as("at"))
      .where("trade_date", "=", today)
      .executeTakeFirst(),
    recentTradingDates(db, 1),
  ]);
  const todayRow = calendar.find((r) => String(r.date) === today);
  const next = calendar.find((r) => String(r.date) > today && r.tradingDay);
  return {
    date: today,
    tradingDay: todayRow ? todayRow.tradingDay : null,
    nextTradingDay: next ? String(next.date) : null,
    lastQuoteAt: quote?.at ? new Date(quote.at).toISOString() : null,
    lastCloseDate: closes[0] ?? null,
  };
}
