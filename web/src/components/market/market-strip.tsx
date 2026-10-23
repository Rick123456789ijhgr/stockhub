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
  // Stat tiles (D-125): label, the value as the headline, then the signed change and date.
  return (
    <ul className="grid grid-cols-2 gap-2 text-sm lg:grid-cols-4">
      {rows.map(({ s, latest }) => (
        <li
          key={s.code}
          className="rounded-lg bg-muted/60 px-3 py-2.5 transition-colors duration-150 hover:bg-muted"
        >
          <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
            <span className="truncate">{s.name}</span>
            <span className="shrink-0 tabular-nums">{latest!.date.slice(5)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-2">
            <span className="text-lg font-semibold tracking-tight">
              {formatSeriesValue(latest!.value, s.unit)}
            </span>
            {latest!.change === null ? null : PRICE_LIKE.has(s.category) ? (
              <PriceChange value={latest!.change * 100} suffix="%" className="text-xs font-medium" />
            ) : (
              <span className="text-xs text-muted-foreground tabular-nums">
                {latest!.change >= 0 ? "+" : "−"}
                {changesInPoints(s)
                  ? Math.abs(latest!.change).toFixed(2)
                  : `${Math.abs(latest!.change * 100).toFixed(2)}%`}
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
