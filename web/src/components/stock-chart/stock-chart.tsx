"use client";

import { useQuery } from "@tanstack/react-query";
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
  TickMarkType,
  type Time,
} from "lightweight-charts";
import { use, useEffect, useId, useMemo, useRef, useState } from "react";

import { cssColor, useThemeVersion } from "@/components/charts/chart-theme";
import { PriceChange } from "@/components/price-change";
import { Skeleton } from "@/components/ui/skeleton";
import {
  adjustedChangePercent,
  type ChartBar,
  type PriceMode,
  RANGES,
  type RangeKey,
  needsFullHistory,
  rangeStartIndex,
  toOhlc,
} from "@/lib/chart-data";
import { kd, macd, rsi, type Series, sma } from "@/lib/indicators";
import { cn } from "@/lib/utils";
import { SEGMENTED_GROUP, segmentedOption } from "@/components/segmented-links";

type IndicatorKey = "KD" | "MACD" | "RSI";
const INDICATORS: IndicatorKey[] = ["KD", "MACD", "RSI"];
const MA_PERIODS = [5, 20, 60] as const;
const SERIES_VARS = ["--series-1", "--series-2", "--series-3"] as const;
/** Swatch classes; using the utilities also keeps the tokens in Tailwind's output. */
const SWATCH_CLASS: Record<(typeof SERIES_VARS)[number], string> = {
  "--series-1": "bg-series-1",
  "--series-2": "bg-series-2",
  "--series-3": "bg-series-3",
};

type Computed = {
  ohlc: ReturnType<typeof toOhlc>;
  ma: Series[];
  indicator: { name: string; values: Series; kind: "line" | "histogram" }[];
};

function compute(bars: ChartBar[], mode: PriceMode, indicator: IndicatorKey): Computed {
  const ohlc = toOhlc(bars, mode);
  const close = ohlc.map((b) => b.close);
  const ma = MA_PERIODS.map((n) => sma(close, n));
  if (indicator === "KD") {
    const r = kd(
      ohlc.map((b) => b.high),
      ohlc.map((b) => b.low),
      close,
    );
    return {
      ohlc,
      ma,
      indicator: [
        { name: "K(9)", values: r.k, kind: "line" },
        { name: "D(9)", values: r.d, kind: "line" },
      ],
    };
  }
  if (indicator === "MACD") {
    const r = macd(close);
    return {
      ohlc,
      ma,
      indicator: [
        { name: "DIF", values: r.dif, kind: "line" },
        { name: "MACD(9)", values: r.signal, kind: "line" },
        { name: "OSC", values: r.histogram, kind: "histogram" },
      ],
    };
  }
  return { ohlc, ma, indicator: [{ name: "RSI(14)", values: rsi(close), kind: "line" }] };
}

function toLine(times: string[], values: Series) {
  return values.flatMap((value, i) => (value === null ? [] : [{ time: times[i], value }]));
}

export type BarsResponse = { bars: ChartBar[]; complete: boolean };

export function StockChartSkeleton() {
  return <Skeleton className="h-[440px] w-full md:h-[560px]" />;
}

async function fetchBars(symbol: string, index: boolean, recent: boolean): Promise<BarsResponse> {
  const query = recent ? "?period=recent" : "";
  const base = index ? "/api/markets" : "/api/stocks";
  const response = await fetch(`${base}/${encodeURIComponent(symbol)}/bars${query}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as BarsResponse;
}

/**
 * `initial`: the recent bars, queried by the page together with the rest of it, so the
 * chart does not wait for a request of its own after the page loads (null when that query
 * failed; the chart then fetches them itself). With `index`, `symbol` is a market series
 * code (TAIEX, TPEX): same chart without the volume pane and price modes, since an index
 * has neither (D-134).
 */
export function StockChart({
  symbol,
  initial,
  index: isIndex = false,
}: {
  symbol: string;
  initial?: Promise<BarsResponse | null>;
  index?: boolean;
}) {
  const initialData = (initial ? use(initial) : null) ?? undefined;
  const [mode, setMode] = useState<PriceMode>("adjusted");
  const [range, setRange] = useState<RangeKey>("1Y");
  const [indicator, setIndicator] = useState<IndicatorKey>("KD");
  const [hovered, setHovered] = useState<number | null>(null);
  const theme = useThemeVersion();
  // Unique per chart: the home page shows two side by side.
  const titleId = useId();

  // The recent years first (small and fast on phones); the whole history only once a
  // longer range is chosen, then it replaces the recent bars.
  const recent = useQuery({
    queryKey: ["bars", isIndex ? "index" : "stock", symbol, "recent"],
    queryFn: () => fetchBars(symbol, isIndex, true),
    staleTime: 60_000,
    initialData,
  });
  const full = useQuery({
    queryKey: ["bars", isIndex ? "index" : "stock", symbol, "all"],
    queryFn: () => fetchBars(symbol, isIndex, false),
    staleTime: 60_000,
    enabled: needsFullHistory(range) && recent.data?.complete === false,
  });
  const data = full.data ?? recent.data;
  const { isPending, isError } = recent;
  const loadingMore = full.isFetching && !full.data;

  const bars = useMemo(() => data?.bars ?? [], [data]);
  const computed = useMemo(() => compute(bars, mode, indicator), [bars, mode, indicator]);

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const rangeRef = useRef(range);
  useEffect(() => {
    rangeRef.current = range;
  }, [range]);

  // (Re)build the chart when the data, mode, indicator or theme changes.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || bars.length === 0) return;
    const color = (name: string, alpha = 1) => cssColor(el, name, alpha);
    const up = color("--price-up");
    const down = color("--price-down");
    const grid = color("--border");
    const text = color("--muted-foreground");
    const series = SERIES_VARS.map((v) => color(v));

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        // No logo on the chart; the attribution the library's NOTICE asks for is on /admin.
        attributionLogo: false,
        textColor: text,
        fontFamily: getComputedStyle(el).fontFamily,
        panes: { separatorColor: grid, separatorHoverColor: grid },
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: grid },
      timeScale: {
        borderColor: grid,
        rightOffset: 3,
        // "2026", "3月", "3/16": the default zh-TW ticks label month starts as "2日".
        tickMarkFormatter: (time: Time, type: TickMarkType) => {
          const [y, m, d] = String(time).split("-").map(Number);
          if (type === TickMarkType.Year) return String(y);
          if (type === TickMarkType.Month) return `${m}月`;
          return `${m}/${d}`;
        },
      },
      localization: { locale: "zh-TW", dateFormat: "yyyy/MM/dd" },
    });
    chartRef.current = chart;
    const times = computed.ohlc.map((b) => b.time);

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
      priceLineVisible: false,
    });
    candles.setData(computed.ohlc);
    computed.ma.forEach((values, i) => {
      chart
        .addSeries(LineSeries, {
          color: series[i],
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        .setData(toLine(times, values));
    });

    if (!isIndex) {
      const volume = chart.addSeries(
        HistogramSeries,
        { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false },
        1,
      );
      volume.setData(
        bars.map(([time, open, , , close, shares]) => ({
          time,
          value: shares / 1000,
          color: close >= open ? color("--price-up", 0.55) : color("--price-down", 0.55),
        })),
      );
    }
    const indicatorPane = isIndex ? 1 : 2;

    computed.indicator.forEach((line, i) => {
      if (line.kind === "histogram") {
        chart
          .addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, indicatorPane)
          .setData(
            toLine(times, line.values).map((p) => ({
              ...p,
              color: p.value >= 0 ? color("--price-up", 0.55) : color("--price-down", 0.55),
            })),
          );
        return;
      }
      const s = chart.addSeries(
        LineSeries,
        { color: series[i], lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        indicatorPane,
      );
      s.setData(toLine(times, line.values));
      if (indicator !== "MACD") {
        for (const level of indicator === "RSI" ? [30, 70] : [20, 80]) {
          s.createPriceLine({
            price: level,
            color: text,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
          });
        }
      }
    });

    const panes = chart.panes();
    panes[0]?.setStretchFactor(3);
    if (isIndex) {
      panes[1]?.setStretchFactor(1.2);
    } else {
      panes[1]?.setStretchFactor(0.8);
      panes[2]?.setStretchFactor(1.2);
    }

    chart.timeScale().setVisibleLogicalRange({
      from: rangeStartIndex(bars, rangeRef.current),
      to: bars.length + 2,
    });

    const onMove = (param: MouseEventParams) => {
      const index = param.logical === undefined ? null : Math.round(param.logical);
      setHovered(index !== null && index >= 0 && index < bars.length ? index : null);
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, computed, indicator, theme, isIndex]);

  // Range buttons only move the visible window.
  useEffect(() => {
    if (bars.length === 0) return;
    chartRef.current?.timeScale().setVisibleLogicalRange({
      from: rangeStartIndex(bars, range),
      to: bars.length + 2,
    });
  }, [range, bars]);

  if (isPending) return <StockChartSkeleton />;
  if (isError) {
    return <p className="text-sm text-muted-foreground">K 線資料載入失敗，請重新整理。</p>;
  }
  if (bars.length === 0) {
    return <p className="text-sm text-muted-foreground">尚無日線資料。</p>;
  }

  const index = hovered ?? bars.length - 1;
  const bar = computed.ohlc[index];
  const change = adjustedChangePercent(bars, index);

  return (
    <section aria-labelledby={titleId}>
      <h2 id={titleId} className="sr-only">
        K 線圖
      </h2>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Toggle
          label="期間"
          options={RANGES.map((r) => ({ key: r.key, label: r.label }))}
          value={range}
          onChange={setRange}
        />
        {isIndex ? null : (
          <Toggle
            label="價格"
            options={[
              { key: "adjusted", label: "還原" },
              { key: "raw", label: "原始" },
            ]}
            value={mode}
            onChange={setMode}
          />
        )}
        <Toggle
          label="指標"
          options={INDICATORS.map((key) => ({ key, label: key }))}
          value={indicator}
          onChange={setIndicator}
        />
        {loadingMore ? (
          <span className="text-xs text-muted-foreground" role="status">
            載入完整歷史…
          </span>
        ) : full.isError ? (
          <span className="text-xs text-muted-foreground" role="status">
            完整歷史載入失敗，目前顯示近 3 年。
          </span>
        ) : null}
      </div>

      <div className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs tabular-nums">
        <span className="font-medium text-foreground">{bar.time}</span>
        <Value label="開" value={bar.open} />
        <Value label="高" value={bar.high} />
        <Value label="低" value={bar.low} />
        <Value label="收" value={bar.close} />
        {change !== null ? <PriceChange value={change} suffix="%" /> : null}
        {isIndex ? null : <Value label="量（張）" value={bars[index][5] / 1000} digits={0} />}
      </div>
      <Legend
        items={MA_PERIODS.map((n, i) => ({
          name: `MA${n}`,
          swatch: SERIES_VARS[i],
          value: computed.ma[i][index],
        }))}
      />
      <div
        ref={containerRef}
        className={cn("w-full touch-pan-y", isIndex ? "h-[380px] md:h-[460px]" : "h-[440px] md:h-[560px]")}
      />
      <Legend
        items={computed.indicator.map((line, i) => ({
          name: line.name,
          swatch: line.kind === "histogram" ? null : SERIES_VARS[i],
          value: line.values[index],
        }))}
      />
      <p className="mt-1 text-xs text-muted-foreground">
        {isIndex ? (
          "證交所與櫃買中心公布的每日指數（2004 年起），收盤後更新。"
        ) : (
          <>
            {mode === "adjusted"
              ? "還原價：舊價格乘上還原因子，換算成今天的股數基礎，除權息與分割不會造成跳空。"
              : "原始價：交易所公布的成交價，除權息日會出現跳空。"}
            成交量為原始股數。均線與指標依目前選擇的價格計算。
          </>
        )}
      </p>
    </section>
  );
}

function Toggle<K extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div role="group" aria-label={label} className={SEGMENTED_GROUP}>
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={option.key === value}
          onClick={() => onChange(option.key)}
          className={cn(segmentedOption(option.key === value), "text-xs font-medium")}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Value({ label, value, digits = 2 }: { label: string; value: number; digits?: number }) {
  return (
    <span className="text-muted-foreground">
      {label} <span className="text-foreground">{value.toFixed(digits)}</span>
    </span>
  );
}

function Legend({
  items,
}: {
  items: { name: string; swatch: (typeof SERIES_VARS)[number] | null; value: number | null }[];
}) {
  return (
    <ul className="mb-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs tabular-nums">
      {items.map((item) => (
        <li key={item.name} className="flex items-center gap-1.5 text-muted-foreground">
          {item.swatch ? (
            <span
              aria-hidden
              className={cn("inline-block h-0.5 w-3 rounded-full", SWATCH_CLASS[item.swatch])}
            />
          ) : null}
          {item.name}
          <span className="text-foreground">
            {item.value === null ? "—" : item.value.toFixed(2)}
          </span>
        </li>
      ))}
    </ul>
  );
}
