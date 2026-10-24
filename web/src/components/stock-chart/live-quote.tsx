"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Star } from "lucide-react";
import { useRouter } from "next/navigation";

import { FlashValue } from "@/components/flash-value";
import { directionClass } from "@/components/price-change";
import { formatHundredMillion, formatLots, formatPrice, formatTaipeiDateTime } from "@/lib/format";
import type { QuoteFundamentals } from "@/lib/fundamentals";
import { isFresherThanDaily, isSessionOpen, type LiveQuote as Quote } from "@/lib/market-hours";
import { priceChange } from "@/lib/price";
import type { DailyBarRow } from "@/lib/stocks";
import { cn } from "@/lib/utils";
import { pbRatio, peRatio } from "@/lib/valuation";

type QuoteResponse = { quote: Quote | null; watched: boolean };

const POLL_MS = 30_000;

/**
 * Snapshots come from the poll_quotes job (watchlist + holdings, every 30 s); the page
 * re-reads them every 30 s while the session is open. The panel and the watch button
 * share one query.
 */
function useQuote(symbol: string) {
  return useQuery({
    queryKey: ["quote", symbol],
    queryFn: async (): Promise<QuoteResponse> => {
      const response = await fetch(`/api/stocks/${encodeURIComponent(symbol)}/quote`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as QuoteResponse;
    },
    refetchInterval: () => (isSessionOpen(new Date()) ? POLL_MS : false),
  });
}

export function WatchButton({ symbol }: { symbol: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { data } = useQuote(symbol);
  const toggle = useMutation({
    mutationFn: async (watch: boolean) => {
      const response = await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, {
        method: watch ? "PUT" : "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["quote", symbol] });
      // Drops the browser's copy of /watchlist (staleTimes, D-118) so it shows the change.
      router.refresh();
    },
  });
  const watched = data?.watched ?? false;
  return (
    <button
      type="button"
      aria-pressed={watched}
      disabled={!data || toggle.isPending}
      onClick={() => toggle.mutate(!watched)}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm disabled:opacity-50"
    >
      <Star aria-hidden className={cn("size-4", watched && "fill-current")} />
      {watched ? "已自選" : "加入自選"}
    </button>
  );
}

/** Which price the header shows: the intraday snapshot when newer than the daily bar. */
function useShownQuote(symbol: string, latest: DailyBarRow | undefined) {
  const { data } = useQuote(symbol);
  const quote = data?.quote ?? null;
  return isFresherThanDaily(quote, latest?.tradeDate ?? null) ? quote : null;
}

/** 「交易中 13:25:30」 or 「收盤 2026/10/20」 under the stock name. */
export function QuoteStatus({ symbol, latest }: { symbol: string; latest: DailyBarRow | undefined }) {
  const live = useShownQuote(symbol, latest);
  if (live) {
    const time = formatTaipeiDateTime(live.quoteTime).slice(11);
    return <span className="tabular-nums">{isSessionOpen(new Date()) ? `交易中 ${time}` : `盤後 ${time}`}</span>;
  }
  if (!latest) return <span>尚無報價</span>;
  return <span className="tabular-nums">收盤 {latest.tradeDate.replaceAll("-", "/")}</span>;
}

/**
 * Price block of the stock page, laid out like Futu's quote header: the price and its
 * change on the left, label-value pairs on the right. High, low and open are colored
 * against the previous close; P/E and P/B follow the valuation tab's rules.
 */
export function QuotePanel({
  symbol,
  latest,
  fundamentals,
  isEtf,
}: {
  symbol: string;
  latest: DailyBarRow | undefined;
  fundamentals: QuoteFundamentals;
  isEtf: boolean;
}) {
  const live = useShownQuote(symbol, latest);
  if (!live && !latest) {
    return (
      <p className="text-sm text-muted-foreground">尚無日線資料。執行 make etl-daily 或回填後再看。</p>
    );
  }
  const bar = live ?? latest!;
  const price = live ? live.price : latest!.close;
  const prevClose = live ? live.prevClose : latest!.prevClose;
  const change = priceChange(price, prevClose);
  const close = price === null ? null : Number(price);
  const ref = prevClose === null ? null : Number(prevClose);
  // Colored like the price: above the previous close is "up".
  const vsPrev = (value: string | null) =>
    value === null || ref === null ? undefined : directionClass(Number(value) - ref);
  const pe = close === null ? null : peRatio(close, fundamentals.epsTtm);
  const pb = close === null ? null : pbRatio(close, fundamentals.bvps);
  const marketCap =
    close === null || fundamentals.issuedShares === null ? null : close * fundamentals.issuedShares;

  // Pairs read in rows: two per row on phones, three on wider screens.
  const stats: { label: string; value: string; className?: string }[] = [
    { label: "最高", value: formatPrice(bar.high), className: vsPrev(bar.high) },
    { label: "今開", value: formatPrice(bar.open), className: vsPrev(bar.open) },
    { label: "最低", value: formatPrice(bar.low), className: vsPrev(bar.low) },
    { label: "昨收", value: formatPrice(prevClose) },
    { label: "成交量", value: `${formatLots(bar.volume)} 張` },
    live
      ? { label: "買／賣", value: `${formatPrice(live.bid)}／${formatPrice(live.ask)}` }
      : { label: "成交額", value: `${formatHundredMillion(latest!.turnover)} 億` },
    ...(isEtf
      ? []
      : [
          { label: "本益比 TTM", value: pe === null ? "—" : pe.toFixed(2) },
          { label: "股價淨值比", value: pb === null ? "—" : pb.toFixed(2) },
        ]),
    { label: "市值", value: formatMarketCap(marketCap) },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-[auto_minmax(0,1fr)] md:items-center md:gap-10">
      <div className={cn(change && directionClass(change.change))}>
        <div className="flex items-center gap-1 text-4xl font-semibold tracking-tight">
          <FlashValue value={close}>{formatPrice(price)}</FlashValue>
          {change && change.change !== 0 ? (
            change.change > 0 ? (
              <ArrowUp className="size-6" aria-label="上漲" />
            ) : (
              <ArrowDown className="size-6" aria-label="下跌" />
            )
          ) : null}
        </div>
        {change ? (
          <div className="mt-1 flex gap-2 text-sm font-medium tabular-nums">
            <span>
              {change.change > 0 ? "+" : ""}
              {change.change.toFixed(2)}
            </span>
            <span>
              {change.percent > 0 ? "+" : ""}
              {change.percent.toFixed(2)}%
            </span>
          </div>
        ) : null}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3 md:border-l md:pl-8">
        {stats.map((s) => (
          <div key={s.label} className="flex items-baseline justify-between gap-2">
            <dt className="shrink-0 text-muted-foreground">{s.label}</dt>
            <dd className={cn("truncate tabular-nums", s.className)}>{s.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Market value in 億, or 兆 from 10,000 億 up (as Futu shows 萬億). */
function formatMarketCap(value: number | null): string {
  if (value === null) return "—";
  return value >= 1e12
    ? `${(value / 1e12).toFixed(2)} 兆`
    : `${formatHundredMillion(value)} 億`;
}
