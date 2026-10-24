import type { Kysely } from "kysely";

import { PriceChange } from "@/components/price-change";
import { StockChart } from "@/components/stock-chart/stock-chart";
import type { DB } from "@/lib/db";
import { formatPrice } from "@/lib/format";
import { getIndexChartBars } from "@/lib/markets";
import { CHART_RECENT_MONTHS } from "@/lib/stocks";

export const INDEXES = { TAIEX: "加權指數", TPEX: "櫃買指數" } as const;
export type IndexCode = keyof typeof INDEXES;

export function parseIndexCode(value: unknown): IndexCode {
  return value === "TPEX" ? "TPEX" : "TAIEX";
}

/**
 * 大盤走勢: the latest close of TAIEX or TPEx, then the same K-line chart as a stock's
 * page (ranges, MA5/20/60, KD/MACD/RSI) without the volume pane (D-134).
 */
export async function IndexOverview({ db, code }: { db: Kysely<DB>; code: IndexCode }) {
  // Shared with the chart, so it does not request the same bars again after the page loads.
  const initial = getIndexChartBars(db, code, CHART_RECENT_MONTHS).catch(() => null);
  const bars = (await initial)?.bars ?? [];
  const last = bars.at(-1);
  const prev = bars.at(-2);
  if (!last) {
    return <p className="text-sm text-muted-foreground">還沒有大盤資料（make etl-markets）。</p>;
  }
  const close = last[4];
  const change = prev ? close - prev[4] : null;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-medium">{INDEXES[code]}</h3>
        <span className="text-2xl font-semibold tracking-tight tabular-nums">{formatPrice(String(close))}</span>
        {change !== null && prev ? (
          <span className="flex gap-2 text-sm font-medium">
            <PriceChange value={change} />
            <PriceChange value={(change / prev[4]) * 100} suffix="%" />
          </span>
        ) : null}
        <span className="text-xs text-muted-foreground tabular-nums">{last[0].replaceAll("-", "/")} 收盤</span>
      </div>
      <StockChart key={code} symbol={code} index initial={initial} />
    </div>
  );
}
