import type { Kysely } from "kysely";

import { PriceChange } from "@/components/price-change";
import { StockChart } from "@/components/stock-chart/stock-chart";
import type { DB } from "@/lib/db";
import { formatPrice } from "@/lib/format";
import { getIndexChartBars } from "@/lib/markets";
import { CHART_RECENT_MONTHS } from "@/lib/stocks";

/** Left to right: TWSE, then TPEx. */
const INDEXES = [
  { code: "TAIEX", name: "加權指數" },
  { code: "TPEX", name: "櫃買指數" },
] as const;

/**
 * 大盤走勢: TAIEX and TPEx side by side (stacked on narrow screens), each its latest close
 * and the same K-line chart as a stock's page (ranges, MA5/20/60, KD/MACD/RSI) without
 * the volume pane (D-134).
 */
export async function IndexOverview({ db }: { db: Kysely<DB> }) {
  // Shared with the charts, so they do not request the same bars again after the page loads.
  const initial = INDEXES.map((i) => getIndexChartBars(db, i.code, CHART_RECENT_MONTHS).catch(() => null));
  const loaded = await Promise.all(initial);
  if (loaded.every((r) => !r?.bars.length)) {
    return <p className="text-sm text-muted-foreground">還沒有大盤資料（make etl-markets）。</p>;
  }
  return (
    <div className="grid gap-x-8 gap-y-10 xl:grid-cols-2">
      {INDEXES.map((index, i) => (
        <IndexChart
          key={index.code}
          code={index.code}
          name={index.name}
          initial={initial[i]!}
          bars={loaded[i]?.bars ?? []}
        />
      ))}
    </div>
  );
}

function IndexChart({
  code,
  name,
  initial,
  bars,
}: {
  code: string;
  name: string;
  initial: ReturnType<typeof getIndexChartBars>;
  bars: NonNullable<Awaited<ReturnType<typeof getIndexChartBars>>>["bars"];
}) {
  const last = bars.at(-1);
  const prev = bars.at(-2);
  const change = last && prev ? last[4] - prev[4] : null;
  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-medium">{name}</h3>
        {last ? (
          <>
            <span className="text-2xl font-semibold tracking-tight tabular-nums">{formatPrice(String(last[4]))}</span>
            {change !== null && prev ? (
              <span className="flex gap-2 text-sm font-medium">
                <PriceChange value={change} />
                <PriceChange value={(change / prev[4]) * 100} suffix="%" />
              </span>
            ) : null}
            <span className="text-xs text-muted-foreground tabular-nums">{last[0].replaceAll("-", "/")} 收盤</span>
          </>
        ) : (
          <span className="text-sm text-muted-foreground">尚無資料</span>
        )}
      </div>
      {last ? <StockChart symbol={code} index initial={initial} /> : null}
    </div>
  );
}
