/**
 * The five-day chart in the stock hover preview (D-132): the last five daily candles on the
 * adjusted basis, so an ex-dividend day does not show as a drop, with today's live quote as
 * the last candle while the market is open. Changes follow the exchange convention: the day
 * against the rebased previous close, the five days against the close before the first one.
 */
import { isFresherThanDaily, type LiveQuote } from "./market-hours";
import { priceChange } from "./price";
import type { DailyBarRow } from "./stocks";

export const PREVIEW_DAYS = 5;

export type PreviewCandle = { date: string; open: number; high: number; low: number; close: number };

export type WeekPreview = {
  candles: PreviewCandle[];
  /** Close before the first candle (same basis): the dashed line and the 5-day base. */
  base: number | null;
  last: number | null;
  change: number | null;
  percent: number | null;
  weekPercent: number | null;
  /** Today's live quote is the last candle. */
  live: boolean;
};

const num = (v: string | null) => (v === null ? null : Number(v));

/** `bars` newest first, as getRecentBars returns them (at least PREVIEW_DAYS + 1 when available). */
export function weekPreview(bars: DailyBarRow[], quote: LiveQuote | null): WeekPreview {
  const live = isFresherThanDaily(quote, bars[0]?.tradeDate ?? null);
  const traded = bars.filter((b) => b.close !== null);
  const daily = traded.slice(0, live ? PREVIEW_DAYS - 1 : PREVIEW_DAYS).reverse();
  // Adjusted price = raw × adj_factor; the newest bar's basis is the reference.
  const adjust = (bar: DailyBarRow, value: string | null) => {
    const v = num(value);
    return v === null ? null : v * Number(bar.adjFactor);
  };
  const candles: PreviewCandle[] = daily.map((bar) => {
    const close = adjust(bar, bar.close)!;
    return {
      date: bar.tradeDate,
      open: adjust(bar, bar.open) ?? close,
      high: adjust(bar, bar.high) ?? close,
      low: adjust(bar, bar.low) ?? close,
      close,
    };
  });
  // The quote is in today's prices; the latest bar's basis matches it unless today is an
  // ex-date, which the quote's own previous close (the reference price) already handles.
  const latestFactor = traded[0] ? Number(traded[0].adjFactor) : 1;
  if (live && quote) {
    const price = Number(quote.price) * latestFactor;
    candles.push({
      date: quote.tradeDate,
      open: (num(quote.open) ?? Number(quote.price)) * latestFactor,
      high: (num(quote.high) ?? Number(quote.price)) * latestFactor,
      low: (num(quote.low) ?? Number(quote.price)) * latestFactor,
      close: price,
    });
  }

  const first = daily[0];
  const base =
    first && first.prevClose !== null
      ? Number(first.prevClose) * Number(first.adjFactor)
      : live && quote && daily.length === 0
        ? num(quote.prevClose)
        : null;
  const day = live && quote ? priceChange(quote.price, quote.prevClose) : traded[0] ? priceChange(traded[0].close, traded[0].prevClose) : null;
  const lastCandle = candles.at(-1);
  const last = live && quote ? Number(quote.price) : traded[0] ? Number(traded[0].close) : null;
  return {
    candles,
    base,
    last,
    change: day?.change ?? null,
    percent: day?.percent ?? null,
    weekPercent: base && lastCandle ? ((lastCandle.close - base) / base) * 100 : null,
    live,
  };
}
