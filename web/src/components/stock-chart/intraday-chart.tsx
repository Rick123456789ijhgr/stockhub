"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BaselineSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  LineStyle,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { cssColor, useThemeVersion } from "@/components/charts/chart-theme";
import { directionClass } from "@/components/price-change";
import { formatPrice } from "@/lib/format";
import {
  chartClock,
  type IntradayDay,
  intradayBase,
  intradayLine,
  showIntraday,
  withDailyReference,
} from "@/lib/intraday";
import { isSessionOpen } from "@/lib/market-hours";
import { priceChange } from "@/lib/price";
import type { DailyBarRow } from "@/lib/stocks";
import { cn } from "@/lib/utils";

const POLL_MS = 30_000;

/**
 * The latest sampled day of the stock (watchlist and holdings only, every 30 s), split at
 * the previous close: up color above it, down color below. `initial` comes with the page;
 * while the session is open the chart re-reads the samples every 30 s.
 */
export function IntradayChart({
  symbol,
  initial,
  latest,
}: {
  symbol: string;
  initial: IntradayDay | null;
  /** The latest daily bar: hides an older day's samples and supplies the reference price. */
  latest: DailyBarRow | undefined;
}) {
  const { data } = useQuery({
    queryKey: ["intraday", symbol],
    queryFn: async (): Promise<IntradayDay | null> => {
      const response = await fetch(`/api/stocks/${encodeURIComponent(symbol)}/intraday`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return ((await response.json()) as { day: IntradayDay | null }).day;
    },
    initialData: initial,
    refetchInterval: () => (isSessionOpen(new Date()) ? POLL_MS : false),
  });
  const day = data ?? null;
  if (!showIntraday(day, latest?.tradeDate ?? null)) return null;
  return <DayChart day={withDailyReference(day, latest)} />;
}

function DayChart({ day }: { day: IntradayDay }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);
  const theme = useThemeVersion();
  const [hover, setHover] = useState<number | null>(null);
  const line = useMemo(() => intradayLine(day), [day]);
  const base = intradayBase(day);

  useEffect(() => {
    const el = ref.current;
    if (!el || base === null) return;
    const color = (name: string, alpha = 1) => cssColor(el, name, alpha);
    const grid = color("--border");
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        // No logo on the chart; the attribution the library's NOTICE asks for is on /admin.
        attributionLogo: false,
        textColor: color("--muted-foreground"),
        fontFamily: getComputedStyle(el).fontFamily,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false },
      localization: {
        locale: "zh-TW",
        priceFormatter: (v: number) => formatPrice(String(v)),
        timeFormatter: (t: Time) => chartClock(Number(t)),
      },
      handleScroll: false,
      handleScale: false,
    });
    const up = "--price-up";
    const down = "--price-down";
    const series = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: base },
      topLineColor: color(up),
      topFillColor1: color(up, 0.25),
      topFillColor2: color(up, 0.04),
      bottomLineColor: color(down),
      bottomFillColor1: color(down, 0.04),
      bottomFillColor2: color(down, 0.25),
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.createPriceLine({
      price: base,
      color: color("--muted-foreground"),
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: day.prevClose === null ? "" : "昨收",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    const onMove = (param: MouseEventParams) => setHover(param.time ? Number(param.time) : null);
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [base, day.prevClose, theme]);

  // New samples every 30 s only replace the data; the chart and the hover stay.
  useEffect(() => {
    seriesRef.current?.setData(line.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chartRef.current?.timeScale().fitContent();
  }, [line, base, theme]);

  const shown = (hover === null ? undefined : line.find((p) => p.time === hover)) ?? line.at(-1);
  const change = shown && day.prevClose !== null ? priceChange(String(shown.value), day.prevClose) : null;

  return (
    <figure className="space-y-1">
      <figcaption className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs">
        <span className="font-medium text-foreground">當日走勢 {day.tradeDate.replaceAll("-", "/")}</span>
        {shown ? (
          <>
            <span className="text-muted-foreground tabular-nums">{chartClock(shown.time).slice(0, 5)}</span>
            <span className={cn("tabular-nums", change && directionClass(change.change))}>
              {formatPrice(String(shown.value))}
              {change ? ` ${change.percent > 0 ? "+" : ""}${change.percent.toFixed(2)}%` : ""}
            </span>
          </>
        ) : null}
        <span className="text-muted-foreground">每 30 秒取樣（自選與持股），保留近幾個交易日</span>
      </figcaption>
      <div ref={ref} style={{ height: 180 }} role="img" aria-label="當日走勢" />
    </figure>
  );
}
