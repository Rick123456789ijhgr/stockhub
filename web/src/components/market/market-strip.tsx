import type { Kysely } from "kysely";

import { PriceChange } from "@/components/price-change";
import type { DB } from "@/lib/db";
import { changesInPoints, formatSeriesValue, latestChange, PRICE_LIKE } from "@/lib/market-series";
import { loadSeries, shiftDate } from "@/lib/markets";

const HOME_SERIES = ["TAIEX", "TPEX", "SPX", "NASDAQ", "SOX", "N225", "USDTWD", "UST10Y"];

/** Home page: latest value and change of the headline series, two columns of rows. */
export async function MarketStrip({ db, today }: { db: Kysely<DB>; today: string }) {
  const series = await loadSeries(db, shiftDate(today, -14), HOME_SERIES);
  const rows = series
    .map((s) => ({ s, latest: latestChange(s.points, changesInPoints(s)) }))
    .filter((r) => r.latest !== null);
  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">還沒有市場資料（make etl-markets）。</p>;
  }
  return (
    <ul className="grid gap-x-6 text-sm sm:grid-cols-2">
      {rows.map(({ s, latest }) => (
        <li key={s.code} className="flex items-baseline justify-between gap-2 border-b py-1.5 last:border-b-0 sm:[&:nth-last-child(2)]:border-b-0">
          <span>
            {s.name}
            <span className="ml-1.5 text-xs text-muted-foreground tabular-nums">{latest!.date.slice(5)}</span>
          </span>
          <span className="flex items-baseline gap-2 tabular-nums">
            {formatSeriesValue(latest!.value, s.unit)}
            {latest!.change === null ? null : PRICE_LIKE.has(s.category) ? (
              <PriceChange value={latest!.change * 100} suffix="%" className="w-16 text-right text-xs" />
            ) : (
              <span className="w-16 text-right text-xs text-muted-foreground">
                {latest!.change >= 0 ? "+" : "−"}
                {changesInPoints(s)
                  ? Math.abs(latest!.change).toFixed(2)
                  : `${Math.abs(latest!.change * 100).toFixed(2)}%`}
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
