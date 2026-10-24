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
  // One row of figures, like a quote board (D-126): scrolls sideways on phones, four even
  // columns on wide screens. Name and date above, the value, then the signed change.
  return (
    <ul className="-mx-4 flex gap-x-7 overflow-x-auto px-4 pb-1 text-sm [scrollbar-width:none] md:mx-0 md:px-0 lg:grid lg:grid-cols-4 lg:gap-y-4 lg:overflow-visible">
      {rows.map(({ s, latest }) => (
        <li key={s.code} className="shrink-0">
          <div className="flex items-baseline gap-2 text-xs text-muted-foreground">
            <span>{s.name}</span>
            <span className="tabular-nums">{latest!.date.slice(5).replace("-", "/")}</span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-2">
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
