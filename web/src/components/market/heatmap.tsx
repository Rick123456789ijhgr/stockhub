"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { type HeatmapGroup, type HeatmapStock, heatBucket, heatColor } from "@/lib/heatmap-data";
import { type Rect, squarify } from "@/lib/treemap";
import { cn } from "@/lib/utils";

const HEADER = 18;
const GAP = 1;
/** Each fill is inset by GAP, so neighbours show a 2px surface gap. */

function pct(change: number | null): string {
  if (change === null) return "—";
  return `${change > 0 ? "+" : ""}${(change * 100).toFixed(2)}%`;
}

function capLabel(cap: number): string {
  return `${(cap / 1e8).toLocaleString("zh-TW", { maximumFractionDigits: 0 })} 億`;
}

type Hover = { stock: HeatmapStock; group: string; x: number; y: number };

function inset(r: Rect, by: number): Rect {
  return {
    x: r.x + by,
    y: r.y + by,
    w: Math.max(0, r.w - 2 * by),
    h: Math.max(0, r.h - 2 * by),
  };
}

function StockTile({
  stock,
  rect,
  days,
  onHover,
}: {
  stock: HeatmapStock;
  rect: Rect;
  days: number;
  onHover: (stock: HeatmapStock | null, e?: React.MouseEvent) => void;
}) {
  const r = inset(rect, GAP);
  const bucket = heatBucket(stock.change, days);
  const showName = r.w >= 44 && r.h >= 22;
  const showChange = r.w >= 44 && r.h >= 36;
  return (
    <Link
      href={`/stocks/${stock.symbol}`}
      aria-label={`${stock.symbol} ${stock.name} ${pct(stock.change)}`}
      onMouseMove={(e) => onHover(stock, e)}
      onMouseLeave={() => onHover(null)}
      className={cn(
        "absolute flex flex-col items-center justify-center overflow-hidden rounded-[2px] text-center leading-tight outline-none focus-visible:ring-2 focus-visible:ring-ring",
        Math.abs(bucket) >= 2 ? "text-white" : "text-foreground",
      )}
      style={{
        left: r.x,
        top: r.y,
        width: r.w,
        height: r.h,
        background: heatColor(bucket),
      }}
    >
      {showName ? (
        <span className="max-w-full truncate px-0.5 text-[11px] font-medium">
          {r.w >= 72 ? stock.name : stock.symbol}
        </span>
      ) : null}
      {showChange ? <span className="text-[10px] tabular-nums">{pct(stock.change)}</span> : null}
    </Link>
  );
}

/**
 * Treemap of groups (industries or themes) and their stocks: area = market cap, colour =
 * change over the period on the diverging up/down scale. Clicking a group header zooms in;
 * clicking a stock opens its page.
 */
export function Heatmap({ groups, days }: { groups: HeatmapGroup[]; days: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const height = width && width < 640 ? 480 : 600;
  const shown = useMemo(() => (focus ? groups.filter((g) => g.key === focus) : groups), [groups, focus]);
  const layout = useMemo(() => {
    if (!width) return [];
    return squarify(shown, (g) => g.marketCap, {
      x: 0,
      y: 0,
      w: width,
      h: height,
    }).map((tile) => {
      const frame = inset(tile, GAP);
      const header = frame.h > 40 && frame.w > 56 ? HEADER : 0;
      const body = {
        x: frame.x,
        y: frame.y + header,
        w: frame.w,
        h: frame.h - header,
      };
      return {
        group: tile.item,
        frame,
        header,
        members: squarify(tile.item.members, (m) => m.marketCap, body),
      };
    });
  }, [shown, width, height]);

  const onHover = (group: string) => (stock: HeatmapStock | null, e?: React.MouseEvent) => {
    if (!stock || !e || !ref.current) return setHover(null);
    const box = ref.current.getBoundingClientRect();
    setHover({
      stock,
      group,
      x: e.clientX - box.left,
      y: e.clientY - box.top,
    });
  };

  return (
    <div className="space-y-2">
      {focus ? (
        <button
          type="button"
          onClick={() => setFocus(null)}
          className="inline-flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="size-4" aria-hidden />
          全部
        </button>
      ) : null}
      <div ref={ref} className="relative w-full overflow-hidden rounded-md bg-background" style={{ height }}>
        {layout.map(({ group, frame, header, members }) => (
          <div key={group.key}>
            {header ? (
              <button
                type="button"
                onClick={() => setFocus(focus ? null : group.key)}
                title={focus ? "回到全部" : `放大 ${group.name}`}
                className="absolute flex items-center gap-1 overflow-hidden px-1 text-left text-[11px] font-medium whitespace-nowrap text-muted-foreground hover:text-foreground"
                style={{
                  left: frame.x,
                  top: frame.y,
                  width: frame.w,
                  height: header,
                }}
              >
                <span className="truncate">{group.name}</span>
                <span className="tabular-nums">{pct(group.change)}</span>
              </button>
            ) : null}
            {members.map((m) => (
              <StockTile key={m.item.id} stock={m.item} rect={m} days={days} onHover={onHover(group.name)} />
            ))}
          </div>
        ))}
        {hover ? (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 min-w-36 rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
            style={{
              left: Math.min(hover.x + 12, Math.max(0, width - 170)),
              top: Math.min(hover.y + 12, height - 80),
            }}
          >
            <div className="font-medium">
              {hover.stock.symbol} {hover.stock.name}
            </div>
            <div className="text-muted-foreground">{hover.group}</div>
            <div className="mt-0.5 flex justify-between gap-3 tabular-nums">
              <span>{pct(hover.stock.change)}</span>
              <span className="text-muted-foreground">市值 {capLabel(hover.stock.marketCap)}</span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Colour scale of the buckets with their thresholds for the period. */
export function HeatmapLegend({ days }: { days: number }) {
  const unit = Math.sqrt(days);
  const f = (x: number) => `${(x * unit).toFixed(x * unit < 1 ? 2 : 1)}%`;
  const steps = [
    { bucket: -3, label: `≤ −${f(2.5)}` },
    { bucket: -2, label: `−${f(1)}` },
    { bucket: -1, label: `−${f(0.25)}` },
    { bucket: 0, label: "持平" },
    { bucket: 1, label: `+${f(0.25)}` },
    { bucket: 2, label: `+${f(1)}` },
    { bucket: 3, label: `≥ +${f(2.5)}` },
  ];
  return (
    <ul
      aria-label="顏色圖例"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground"
    >
      {steps.map((s) => (
        <li key={s.bucket} className="flex items-center gap-1">
          <span
            className="inline-block size-3 rounded-[2px]"
            style={{ background: heatColor(s.bucket) }}
            aria-hidden
          />
          <span className="tabular-nums">{s.label}</span>
        </li>
      ))}
    </ul>
  );
}
