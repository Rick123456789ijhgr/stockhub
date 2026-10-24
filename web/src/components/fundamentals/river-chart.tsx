"use client";

import { useMemo, useState } from "react";

import { type ChartSeries, TimeChart } from "@/components/charts/time-chart";
import { cn } from "@/lib/utils";
import { SEGMENTED_GROUP, segmentedOption } from "@/components/segmented-links";
import {
  bandMultiples,
  metricValues,
  riverBands,
  type ValuationPoint,
} from "@/lib/valuation";

/** One hue in light-to-dark steps (sequential), behind the close in the foreground ink. */
const BAND_ALPHA = [0.3, 0.45, 0.6, 0.75, 0.9];

function Toggle<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn(SEGMENTED_GROUP, "text-xs")}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={segmentedOption(o.value === value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 本益比／股價淨值比河流圖: close vs TTM EPS (or book value) x multiples of the window. */
export function RiverChart({ points, hasPe }: { points: ValuationPoint[]; hasPe: boolean }) {
  const [metric, setMetric] = useState<"pe" | "pb">(hasPe ? "pe" : "pb");

  const { series, multiples } = useMemo(() => {
    // The section passes the fixed five-year window (lib/financial-window).
    const shown = points;
    const multiples = bandMultiples(metricValues(shown, metric));
    const bands = riverBands(shown, metric, multiples);
    const out: ChartSeries[] = multiples.map((m, i) => ({
      name: `${m.toFixed(1)} 倍`,
      kind: "line",
      color: "--series-1",
      alpha: BAND_ALPHA[i] ?? 0.6,
      width: 1,
      data: shown.map((p, j) => ({ time: p.date, value: bands[j][i] })),
    }));
    out.push({
      name: "收盤",
      kind: "line",
      color: "--foreground",
      width: 2,
      data: shown.map((p) => ({ time: p.date, value: p.close })),
    });
    return { series: out, multiples };
  }, [points, metric]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Toggle
          label="河流圖指標"
          value={metric}
          onChange={setMetric}
          options={[
            ...(hasPe ? [{ value: "pe" as const, label: "本益比" }] : []),
            { value: "pb" as const, label: "股價淨值比" },
          ]}
        />
      </div>
      {multiples.length === 0 ? (
        <p className="text-sm text-muted-foreground">這段期間沒有可用的{metric === "pe" ? "獲利" : "淨值"}資料。</p>
      ) : (
        <TimeChart
          label={metric === "pe" ? "本益比河流圖" : "股價淨值比河流圖"}
          format="price"
          height={300}
          series={series}
        />
      )}
      <p className="text-xs text-muted-foreground">
        倍數取這段期間{metric === "pe" ? "本益比（排除虧損期）" : "股價淨值比"}的第 5 到第 95
        百分位等距五條；價格 = {metric === "pe" ? "近四季 EPS" : "每股淨值"} × 倍數，財報在公布日（不明時用法定截止日）之後才採用。
      </p>
    </div>
  );
}
