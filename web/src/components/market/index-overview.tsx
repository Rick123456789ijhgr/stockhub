import type { Kysely } from "kysely";

import { TimeChart } from "@/components/charts/time-chart";
import { PriceChange } from "@/components/price-change";
import { Card, CardContent } from "@/components/ui/card";
import type { DB } from "@/lib/db";
import { formatPrice } from "@/lib/format";
import { sma } from "@/lib/indicators";
import { type IndexBar, loadIndexBars, shiftDate } from "@/lib/markets";

export const INDEX_RANGES = { "3m": 92, "6m": 183, "1y": 366, "3y": 1096 } as const;
export type IndexRange = keyof typeof INDEX_RANGES;
export const INDEX_RANGE_LABEL: Record<IndexRange, string> = {
  "3m": "3 個月",
  "6m": "6 個月",
  "1y": "1 年",
  "3y": "3 年",
};

export function parseIndexRange(value: unknown): IndexRange {
  return typeof value === "string" && value in INDEX_RANGES ? (value as IndexRange) : "6m";
}

const INDEXES = [
  { code: "TAIEX", name: "加權指數" },
  { code: "TPEX", name: "櫃買指數" },
];

/** Calendar days loaded before the range so MA60 starts at its left edge. */
const WARM_UP_DAYS = 120;

/** 大盤走勢: TAIEX and TPEx daily candles with MA20 and MA60, side by side on wide screens. */
export async function IndexOverview({
  db,
  today,
  range,
}: {
  db: Kysely<DB>;
  today: string;
  range: IndexRange;
}) {
  const days = INDEX_RANGES[range];
  const since = shiftDate(today, -days);
  const all = await Promise.all(
    INDEXES.map((i) => loadIndexBars(db, i.code, shiftDate(since, -WARM_UP_DAYS))),
  );
  if (all.every((bars) => bars.length === 0)) {
    return <p className="text-sm text-muted-foreground">還沒有大盤資料（make etl-markets）。</p>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {INDEXES.map((index, i) => (
        <IndexCard key={index.code} name={index.name} bars={all[i]!} since={since} range={range} />
      ))}
    </div>
  );
}

function IndexCard({
  name,
  bars,
  since,
  range,
}: {
  name: string;
  bars: IndexBar[];
  since: string;
  range: IndexRange;
}) {
  const closes = bars.map((b) => b.close);
  const [ma20, ma60] = [sma(closes, 20), sma(closes, 60)];
  const start = Math.max(0, bars.findIndex((b) => b.date >= since));
  const shown = bars.slice(start);
  const last = bars.at(-1);
  const prev = bars.at(-2);
  // The range's change runs from the close before its first bar.
  const base = bars[start - 1] ?? shown[0];
  const line = (values: (number | null)[]) =>
    shown.map((b, j) => ({ time: b.date, value: values[start + j] ?? null }));
  return (
    <Card size="sm">
      <CardContent className="space-y-3">
        {last ? (
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <h3 className="text-sm font-medium">{name}</h3>
              <span className="text-2xl font-semibold tracking-tight tabular-nums">
                {formatPrice(String(last.close))}
              </span>
              {prev ? (
                <span className="flex gap-2 text-sm font-medium">
                  <PriceChange value={last.close - prev.close} />
                  <PriceChange value={((last.close - prev.close) / prev.close) * 100} suffix="%" />
                </span>
              ) : null}
            </div>
            <span className="flex gap-3 text-xs text-muted-foreground tabular-nums">
              {base ? (
                <span>
                  {INDEX_RANGE_LABEL[range]} <PriceChange value={((last.close - base.close) / base.close) * 100} suffix="%" />
                </span>
              ) : null}
              <span>{last.date.replaceAll("-", "/")} 收盤</span>
            </span>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{name}尚無資料</p>
        )}
        {shown.length > 1 ? (
          <TimeChart
            label="日線"
            format="price"
            height={240}
            series={[
              {
                name: "收盤",
                kind: "candle",
                color: "--foreground",
                data: shown.map((b) => ({ time: b.date, value: b.close })),
                ohlc: shown.map((b) => ({ time: b.date, open: b.open, high: b.high, low: b.low, close: b.close })),
              },
              { name: "MA20", kind: "line", color: "--series-1", width: 1, data: line(ma20) },
              { name: "MA60", kind: "line", color: "--series-2", width: 1, data: line(ma60) },
            ]}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
