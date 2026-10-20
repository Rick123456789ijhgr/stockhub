"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { PriceChange } from "@/components/price-change";
import { formatHundredMillion, formatLots, formatPrice, formatTaipeiDateTime } from "@/lib/format";
import { isFresherThanDaily, isSessionOpen, type LiveQuote as Quote } from "@/lib/market-hours";
import { priceChange } from "@/lib/price";
import type { DailyBarRow } from "@/lib/stocks";
import { cn } from "@/lib/utils";

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
  const { data } = useQuote(symbol);
  const toggle = useMutation({
    mutationFn: async (watch: boolean) => {
      const response = await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, {
        method: watch ? "PUT" : "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["quote", symbol] }),
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

/**
 * Price block of the stock page: the intraday snapshot when it is newer than the latest
 * daily bar, otherwise that bar's close.
 */
export function QuotePanel({ symbol, latest }: { symbol: string; latest: DailyBarRow | undefined }) {
  const { data } = useQuote(symbol);
  const quote = data?.quote ?? null;
  const live = isFresherThanDaily(quote, latest?.tradeDate ?? null) ? quote : null;

  if (!live && !latest) {
    return (
      <p className="text-sm text-muted-foreground">尚無日線資料。執行 make etl-daily 或回填後再看。</p>
    );
  }
  const price = live ? live.price : latest!.close;
  const prevClose = live ? live.prevClose : latest!.prevClose;
  const change = priceChange(price, prevClose);
  const stats = live
    ? [
        { label: "開盤", value: formatPrice(live.open) },
        { label: "最高", value: formatPrice(live.high) },
        { label: "最低", value: formatPrice(live.low) },
        { label: "昨收", value: formatPrice(live.prevClose) },
        { label: "買進", value: formatPrice(live.bid) },
        { label: "賣出", value: formatPrice(live.ask) },
        { label: "累計量（張）", value: formatLots(live.volume) },
      ]
    : [
        { label: "開盤", value: formatPrice(latest!.open) },
        { label: "最高", value: formatPrice(latest!.high) },
        { label: "最低", value: formatPrice(latest!.low) },
        { label: "昨收", value: formatPrice(latest!.prevClose) },
        { label: "成交量（張）", value: formatLots(latest!.volume) },
        { label: "成交金額（億）", value: formatHundredMillion(latest!.turnover) },
      ];

  return (
    <div className="flex flex-col gap-3 md:flex-row md:items-center md:gap-8">
      <div className="shrink-0">
        <div className="flex items-baseline gap-2 tabular-nums">
          <span className="text-3xl font-semibold tracking-tight">{formatPrice(price)}</span>
          {change ? (
            <span className="flex gap-2 text-sm">
              <PriceChange value={change.change} />
              <PriceChange value={change.percent} suffix="%" />
            </span>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground tabular-nums">
          {live
            ? `盤中 ${formatTaipeiDateTime(live.quoteTime).slice(11)} 成交 · 每 30 秒更新`
            : `收盤 ${latest!.tradeDate}`}
        </p>
      </div>
      <dl className="grid flex-1 grid-cols-3 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-4 lg:grid-cols-7">
        {stats.map((s) => (
          <div key={s.label}>
            <dt className="text-xs text-muted-foreground">{s.label}</dt>
            <dd className="tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
