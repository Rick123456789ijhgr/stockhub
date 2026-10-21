import { TimeChart } from "@/components/charts/time-chart";
import { PriceChange } from "@/components/price-change";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ValueFormat } from "@/lib/chart-format";
import {
  changesInPoints,
  formatSeriesValue,
  latestChange,
  percentToFraction,
  PRICE_LIKE,
} from "@/lib/market-series";
import type { LoadedSeries } from "@/lib/markets";
import { cn } from "@/lib/utils";

/** Latest value, change against the previous observation, and a one-year line. */
export function SeriesCard({ series, chartHeight = 110 }: { series: LoadedSeries; chartHeight?: number }) {
  const inPoints = changesInPoints(series);
  const latest = latestChange(series.points, inPoints);
  const percent = series.unit === "percent";
  const format: ValueFormat = percent ? "percent" : "price";
  const data = (percent ? percentToFraction(series.points) : series.points).map((p) => ({
    time: p.date,
    value: p.value,
  }));
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="flex items-baseline justify-between gap-2 text-sm">
          <span>{series.name}</span>
          {latest ? (
            <span className="text-xs font-normal text-muted-foreground tabular-nums">{latest.date}</span>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {latest ? (
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tabular-nums">
              {formatSeriesValue(latest.value, series.unit)}
            </span>
            {latest.change !== null ? (
              PRICE_LIKE.has(series.category) ? (
                <PriceChange value={latest.change * 100} suffix="%" className="text-sm" />
              ) : (
                <span className={cn("text-sm text-muted-foreground tabular-nums")}>
                  {latest.change >= 0 ? "+" : "−"}
                  {inPoints
                    ? `${Math.abs(latest.change).toFixed(2)}${percent ? " 個百分點" : ""}`
                    : `${Math.abs(latest.change * 100).toFixed(2)}%`}
                </span>
              )
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">尚無資料</p>
        )}
        {data.length > 1 ? (
          <TimeChart
            label={series.name}
            format={format}
            height={chartHeight}
            period={series.frequency === "monthly" ? "month" : "day"}
            series={[
              {
                name: series.name,
                kind: "line",
                color: "--series-1",
                width: 2,
                data,
              },
            ]}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
