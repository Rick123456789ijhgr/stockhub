"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PriceChange } from "@/components/price-change";
import { formatPrice } from "@/lib/format";
import { PREVIEW_HEIGHT, PREVIEW_WIDTH, previewPosition, previewSymbol } from "@/lib/stock-preview";
import { cn } from "@/lib/utils";
import type { WeekPreview } from "@/lib/week-preview";

/** Hover this long before the preview opens, so moving the pointer across a list shows nothing. */
const OPEN_DELAY_MS = 350;

type WeekResponse = WeekPreview & { symbol: string; name: string; market: string; isEtf: boolean };

function weekQuery(symbol: string) {
  return {
    queryKey: ["stock-week", symbol],
    queryFn: async (): Promise<WeekResponse> => {
      const res = await fetch(`/api/stocks/${encodeURIComponent(symbol)}/week`);
      if (!res.ok) throw new Error(`week ${res.status}`);
      return res.json();
    },
    staleTime: 60_000,
    retry: false,
  };
}

type Target = { symbol: string; left: number; top: number; above: boolean };

/**
 * The five-day preview for any link to a stock page, anywhere on the site (D-132). One
 * delegated listener on the document, so lists, tables and text links need no changes.
 * Mouse only; it opens after a short hover, closes the moment the pointer leaves the link,
 * and never takes the pointer itself. Data is prefetched on hover, before the delay ends.
 */
export function StockHoverPreview() {
  const queryClient = useQueryClient();
  const pathname = usePathname();
  const [target, setTarget] = useState<Target | null>(null);
  const anchorRef = useRef<HTMLAnchorElement | null>(null);
  const timerRef = useRef<number | undefined>(undefined);

  // A new page closes whatever was open (the link may be gone without a pointerout).
  const [seenPath, setSeenPath] = useState(pathname);
  if (seenPath !== pathname) {
    setSeenPath(pathname);
    setTarget(null);
  }

  useEffect(() => {
    const hide = () => {
      window.clearTimeout(timerRef.current);
      anchorRef.current = null;
      setTarget(null);
    };
    const onOver = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement) || anchor === anchorRef.current) return;
      if (anchor.closest("[data-no-stock-preview]")) return;
      const symbol = previewSymbol(anchor.href, window.location);
      if (!symbol) return;
      hide();
      anchorRef.current = anchor;
      void queryClient.prefetchQuery(weekQuery(symbol));
      timerRef.current = window.setTimeout(() => {
        if (anchorRef.current !== anchor || !anchor.isConnected) return;
        const rect = anchor.getBoundingClientRect();
        setTarget({ symbol, ...previewPosition(rect, { width: window.innerWidth, height: window.innerHeight }) });
      }, OPEN_DELAY_MS);
    };
    const onOut = (event: PointerEvent) => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      if (event.relatedTarget instanceof Node && anchor.contains(event.relatedTarget)) return;
      if (event.target instanceof Node && anchor.contains(event.target)) hide();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    document.addEventListener("pointerover", onOver);
    document.addEventListener("pointerout", onOut);
    document.addEventListener("pointerdown", hide);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, { capture: true, passive: true });
    window.addEventListener("blur", hide);
    return () => {
      window.clearTimeout(timerRef.current);
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("pointerout", onOut);
      document.removeEventListener("pointerdown", hide);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, { capture: true });
      window.removeEventListener("blur", hide);
    };
  }, [queryClient]);

  if (!target) return null;
  return <PreviewCard target={target} />;
}

function PreviewCard({ target }: { target: Target }) {
  const { data, isError } = useQuery(weekQuery(target.symbol));
  if (isError) return null;
  return (
    <div
      role="tooltip"
      className={cn(
        "stock-preview pointer-events-none fixed z-50 flex flex-col gap-2 rounded-lg border bg-popover p-3 text-popover-foreground shadow-card-hover",
        target.above ? "origin-bottom-left" : "origin-top-left",
      )}
      style={{ left: target.left, top: target.top, width: PREVIEW_WIDTH, height: PREVIEW_HEIGHT }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <p className="min-w-0 truncate text-sm">
          <span className="font-semibold tabular-nums">{target.symbol}</span> {data?.name ?? ""}
        </p>
        {data ? <span className="shrink-0 text-xs text-muted-foreground">{data.isEtf ? "ETF" : data.market}</span> : null}
      </div>
      {data ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tabular-nums">{formatPrice(data.last === null ? null : String(data.last))}</span>
            {data.percent !== null ? <PriceChange value={data.percent} suffix="%" className="text-xs" /> : null}
            {data.live ? <span className="ml-auto text-[11px] text-muted-foreground">盤中</span> : null}
          </div>
          <Candles data={data} />
        </>
      ) : (
        <div className="flex-1 animate-pulse rounded-md bg-muted" aria-label="載入中" />
      )}
    </div>
  );
}

const CHART_H = 64;
const LABEL_H = 14;

/**
 * Five daily candles (red up, green down by the price tokens) over a dashed line at the
 * close before them, so the five days' net move reads at a glance.
 */
function Candles({ data }: { data: WeekResponse }) {
  const { candles, base, weekPercent } = data;
  if (candles.length === 0) return <p className="text-xs text-muted-foreground">沒有近期日線。</p>;
  const width = PREVIEW_WIDTH - 24;
  const values = candles.flatMap((c) => [c.high, c.low]).concat(base === null ? [] : [base]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const y = (v: number) => (max === min ? CHART_H / 2 : 2 + ((max - v) / (max - min)) * (CHART_H - 4));
  const slot = width / 5;
  const body = Math.max(4, slot * 0.38);
  return (
    <div className="space-y-1">
      <svg width={width} height={CHART_H + LABEL_H} role="img" aria-label="近 5 個交易日 K 線">
        {base !== null ? (
          <line x1={0} x2={width} y1={y(base)} y2={y(base)} strokeDasharray="3 3" className="stroke-muted-foreground/50" />
        ) : null}
        {candles.map((c, i) => {
          const cx = slot * (i + 0.5);
          const up = c.close >= c.open;
          const top = y(Math.max(c.open, c.close));
          const h = Math.max(1, Math.abs(y(c.open) - y(c.close)));
          const tone = up ? "fill-up stroke-up" : "fill-down stroke-down";
          return (
            <g key={c.date} className={tone}>
              <line x1={cx} x2={cx} y1={y(c.high)} y2={y(c.low)} strokeWidth={1} />
              <rect x={cx - body / 2} y={top} width={body} height={h} rx={1} strokeWidth={0} />
              <text
                x={cx}
                y={CHART_H + LABEL_H - 2}
                textAnchor="middle"
                className="fill-muted-foreground stroke-none text-[10px] tabular-nums"
              >
                {c.date.slice(5).replace("-", "/")}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="flex justify-between text-[11px] text-muted-foreground">
        <span>近 5 日</span>
        {weekPercent !== null ? <PriceChange value={weekPercent} suffix="%" /> : null}
      </p>
    </div>
  );
}
