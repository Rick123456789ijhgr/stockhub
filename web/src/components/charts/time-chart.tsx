"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  LineSeries,
  LineStyle,
  type MouseEventParams,
  type Time,
  TickMarkType,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { axisFormat, formatValue, type Period, periodLabel, type ValueFormat } from "@/lib/chart-format";
import { cn } from "@/lib/utils";

import { cssColor, useThemeVersion } from "./chart-theme";

export type ColorToken = "--series-1" | "--series-2" | "--series-3" | "--foreground" | "--muted-foreground";

export type ChartSeries = {
  name: string;
  /** Candles take the price colors (`ohlc`); the legend shows `data`, their closes. */
  kind: "line" | "histogram" | "candle";
  color: ColorToken;
  /** 0..1 opacity, e.g. river bands as one hue in light-to-dark steps. */
  alpha?: number;
  width?: 1 | 2 | 3;
  dashed?: boolean;
  /** Shown in the legend; bands without their own entry set it false. */
  legend?: boolean;
  /** Histogram bars take the price colors by sign (buying up, selling down) instead of `color`. */
  signed?: boolean;
  data: { time: string; value: number | null }[];
  /** Bars of a "candle" series. */
  ohlc?: { time: string; open: number; high: number; low: number; close: number }[];
};

/** Swatch classes; using the utilities keeps the tokens in Tailwind's output. */
const SWATCH: Record<ColorToken, string> = {
  "--series-1": "bg-series-1",
  "--series-2": "bg-series-2",
  "--series-3": "bg-series-3",
  "--foreground": "bg-foreground",
  "--muted-foreground": "bg-muted-foreground",
};

/**
 * Small time-series chart on lightweight-charts (same look as the K-line chart): lines
 * and/or histograms on one value axis, crosshair with an HTML legend that shows the
 * values under the cursor (the latest values otherwise). Colors come from tokens only.
 */
export function TimeChart({
  series,
  format,
  height = 220,
  label,
  period = "day",
  className,
}: {
  series: ChartSeries[];
  format: ValueFormat;
  height?: number;
  label: string;
  period?: Period;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const theme = useThemeVersion();
  const [hover, setHover] = useState<string | null>(null);

  const lookup = useMemo(
    () =>
      series.map((s) => new Map(s.data.map((p) => [p.time, p.value] as [string, number | null]))),
    [series],
  );
  const lastTime = useMemo(() => {
    let last = "";
    for (const s of series) for (const p of s.data) if (p.value !== null && p.time > last) last = p.time;
    return last;
  }, [series]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
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
      timeScale: {
        borderColor: grid,
        // Years of daily points must fit a card: the default minimum (0.5 px per bar) would
        // make fitContent silently show only the latest stretch.
        minBarSpacing: 0.05,
        tickMarkFormatter: (time: Time, type: TickMarkType) => {
          const [y, m] = String(time).split("-").map(Number);
          return type === TickMarkType.Year ? String(y) : `${m}月`;
        },
      },
      localization: {
        locale: "zh-TW",
        priceFormatter: (v: number) => axisFormat(v, format),
      },
      handleScroll: { vertTouchDrag: false },
    });
    chartRef.current = chart;
    for (const s of series) {
      const data = s.data.flatMap((p) => (p.value === null ? [] : [{ time: p.time as Time, value: p.value }]));
      const tint = color(s.color, s.alpha ?? 1);
      if (s.kind === "candle") {
        const up = color("--price-up");
        const down = color("--price-down");
        chart
          .addSeries(CandlestickSeries, {
            upColor: up,
            downColor: down,
            borderUpColor: up,
            borderDownColor: down,
            wickUpColor: up,
            wickDownColor: down,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          .setData((s.ohlc ?? []).map((b) => ({ ...b, time: b.time as Time })));
      } else if (s.kind === "histogram") {
        const up = color("--price-up");
        const down = color("--price-down");
        const bars = s.signed ? data.map((p) => ({ ...p, color: p.value >= 0 ? up : down })) : data;
        chart.addSeries(HistogramSeries, { color: tint, priceLineVisible: false, lastValueVisible: false }).setData(bars);
      } else {
        chart
          .addSeries(LineSeries, {
            color: tint,
            lineWidth: s.width ?? 2,
            lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: s.legend !== false,
          })
          .setData(data);
      }
    }
    chart.timeScale().fitContent();
    const onMove = (param: MouseEventParams) =>
      setHover(param.time ? String(param.time) : null);
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [series, format, theme]);

  const at = hover ?? lastTime;
  const legend = series
    .map((s, i) => ({ s, value: lookup[i].get(at) ?? null }))
    .filter(({ s }) => s.legend !== false);

  return (
    <figure className={cn("space-y-1", className)}>
      <figcaption className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs">
        <span className="font-medium text-foreground">{label}</span>
        {at ? <span className="text-muted-foreground tabular-nums">{periodLabel(at, period)}</span> : null}
        {legend.map(({ s, value }) => (
          <span key={s.name} className="inline-flex items-center gap-1 text-muted-foreground">
            {s.signed || s.kind === "candle" ? (
              <span className="inline-flex h-2 w-3 overflow-hidden rounded-sm" aria-hidden>
                <span className="w-1/2 bg-up" />
                <span className="w-1/2 bg-down" />
              </span>
            ) : (
              <span className={cn("inline-block h-0.5 w-3 rounded", SWATCH[s.color])} aria-hidden />
            )}
            {s.name}
            <span className="text-foreground tabular-nums">{formatValue(value, format)}</span>
          </span>
        ))}
      </figcaption>
      <div ref={ref} style={{ height }} role="img" aria-label={label} />
    </figure>
  );
}
