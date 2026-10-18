"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";

import { PriceChange } from "@/components/price-change";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatLots, formatPrice, formatTaipeiDateTime } from "@/lib/format";
import { isFresherThanDaily, isSessionOpen, type LiveQuote as Quote } from "@/lib/market-hours";
import { priceChange } from "@/lib/price";
import { cn } from "@/lib/utils";

type QuoteResponse = { quote: Quote | null; watched: boolean };

const POLL_MS = 30_000;

/**
 * Intraday card plus the watchlist toggle. Snapshots come from the poll_quotes job
 * (watchlist + holdings, every 30 s); the page re-reads them every 30 s while the
 * session is open.
 */
export function LiveQuote({
  symbol,
  latestBarDate,
  canWatch,
}: {
  symbol: string;
  latestBarDate: string | null;
  canWatch: boolean;
}) {
  const queryClient = useQueryClient();
  const key = ["quote", symbol];
  const { data } = useQuery({
    queryKey: key,
    queryFn: async (): Promise<QuoteResponse> => {
      const response = await fetch(`/api/stocks/${encodeURIComponent(symbol)}/quote`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as QuoteResponse;
    },
    refetchInterval: () => (isSessionOpen(new Date()) ? POLL_MS : false),
  });
  const toggle = useMutation({
    mutationFn: async (watch: boolean) => {
      const response = await fetch(`/api/watchlist/${encodeURIComponent(symbol)}`, {
        method: watch ? "PUT" : "DELETE",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  const watched = data?.watched ?? false;
  const quote = data?.quote ?? null;
  const fresh = isFresherThanDaily(quote, latestBarDate);

  return (
    <div className="mb-4">
      {canWatch ? (
        <button
          type="button"
          aria-pressed={watched}
          disabled={!data || toggle.isPending}
          onClick={() => toggle.mutate(!watched)}
          className="mb-3 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          <Star
            aria-hidden
            className={cn("size-4", watched && "fill-current")}
          />
          {watched ? "已加入自選" : "加入自選"}
        </button>
      ) : null}
      {fresh && quote ? <QuoteCard quote={quote} /> : null}
      {canWatch && watched && !fresh ? (
        <p className="text-xs text-muted-foreground">
          盤中報價由排程任務 poll_quotes 每 30 秒更新自選股與持股（本機：make etl-quotes）。
        </p>
      ) : null}
    </div>
  );
}

function QuoteCard({ quote }: { quote: Quote }) {
  const change = priceChange(quote.price, quote.prevClose);
  return (
    <Card>
      <CardHeader>
        <CardDescription>
          盤中（{formatTaipeiDateTime(quote.quoteTime).slice(11)} 成交，每 30 秒更新）
        </CardDescription>
        <CardTitle className="flex items-baseline gap-3 text-2xl tabular-nums">
          {formatPrice(quote.price)}
          {change ? (
            <span className="text-base">
              <PriceChange value={change.change} /> <PriceChange value={change.percent} suffix="%" />
            </span>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-2 text-sm sm:grid-cols-6">
        <Stat label="開盤" value={formatPrice(quote.open)} />
        <Stat label="最高" value={formatPrice(quote.high)} />
        <Stat label="最低" value={formatPrice(quote.low)} />
        <Stat label="買進" value={formatPrice(quote.bid)} />
        <Stat label="賣出" value={formatPrice(quote.ask)} />
        <Stat label="累計量（張）" value={formatLots(quote.volume)} />
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular-nums">{value}</div>
    </div>
  );
}
