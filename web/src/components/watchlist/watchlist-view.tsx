"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PriceChange } from "@/components/price-change";
import { Button } from "@/components/ui/button";
import { formatPrice, formatTaipeiDateTime } from "@/lib/format";
import type { WatchItem } from "@/lib/watchlist";
import { moveSymbol, SORT_KEYS, SORT_LABEL, type SortKey, sortWatchlist } from "@/lib/watchlist-sort";

async function send(url: string, method: string, body?: unknown): Promise<void> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.status === 404 ? "找不到這個代號" : `HTTP ${response.status}`);
}

/** Watchlist with add, remove, notes, column sorting and a custom (up/down) order. */
export function WatchlistView({ items }: { items: WatchItem[] }) {
  const router = useRouter();
  const [sort, setSort] = useState<SortKey>("custom");
  const [desc, setDesc] = useState(false);
  const [symbol, setSymbol] = useState("");

  const rows = sortWatchlist(
    items.map((item) => {
      const m = item.mark;
      const changePercent =
        m && m.prevClose ? ((m.price - m.prevClose) / m.prevClose) * 100 : null;
      return { ...item, price: m?.price ?? null, changePercent };
    }),
    sort,
    desc,
  );
  const order = items.map((i) => i.symbol);

  const mutate = useMutation({
    mutationFn: (args: { url: string; method: string; body?: unknown }) =>
      send(args.url, args.method, args.body),
    onSuccess: () => router.refresh(),
  });
  const add = useMutation({
    mutationFn: (s: string) => send(`/api/watchlist/${encodeURIComponent(s)}`, "PUT"),
    onSuccess: () => {
      setSymbol("");
      router.refresh();
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (symbol.trim()) add.mutate(symbol.trim().toUpperCase());
          }}
        >
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="代號，例如 2330"
            aria-label="加入自選的代號"
            autoComplete="off"
            className="h-8 w-36 rounded-md border bg-background px-2 text-sm"
          />
          <Button type="submit" variant="outline" disabled={add.isPending}>
            <Plus aria-hidden />
            加入
          </Button>
        </form>
        <div className="flex items-center gap-2 text-sm">
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            排序
            <select
              value={sort}
              onChange={(e) => {
                const key = e.target.value as SortKey;
                setSort(key);
                setDesc(key === "change" || key === "added");
              }}
              className="h-8 rounded-md border bg-background px-2 text-sm text-foreground"
            >
              {SORT_KEYS.map((k) => (
                <option key={k} value={k}>
                  {SORT_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          {sort !== "custom" ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={desc ? "由大到小（切換）" : "由小到大（切換）"}
              onClick={() => setDesc((d) => !d)}
            >
              {desc ? <ArrowDown aria-hidden /> : <ArrowUp aria-hidden />}
            </Button>
          ) : null}
        </div>
      </div>
      {add.isError ? <p className="text-xs text-destructive">{add.error.message}</p> : null}
      {mutate.isError ? <p className="text-xs text-destructive">儲存失敗，請重新整理後再試。</p> : null}

      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          還沒有自選股。在這裡輸入代號，或在個股頁按「加入自選」。
        </p>
      ) : (
        <ul className="divide-y">
          {rows.map((item, index) => (
            <li key={item.symbol} className="flex items-start gap-2 py-2 text-sm">
              {sort === "custom" ? (
                <div className="flex shrink-0 flex-col">
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`${item.symbol} 上移`}
                    disabled={index === 0 || mutate.isPending}
                    onClick={() =>
                      mutate.mutate({
                        url: "/api/watchlist/order",
                        method: "PUT",
                        body: { symbols: moveSymbol(order, item.symbol, -1) },
                      })
                    }
                  >
                    <ArrowUp aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`${item.symbol} 下移`}
                    disabled={index === rows.length - 1 || mutate.isPending}
                    onClick={() =>
                      mutate.mutate({
                        url: "/api/watchlist/order",
                        method: "PUT",
                        body: { symbols: moveSymbol(order, item.symbol, 1) },
                      })
                    }
                  >
                    <ArrowDown aria-hidden />
                  </Button>
                </div>
              ) : null}
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-baseline justify-between gap-2">
                  <Link href={`/stocks/${item.symbol}`} className="truncate font-medium hover:underline">
                    <span className="font-mono">{item.symbol}</span> {item.name}
                    {item.type === "etf" ? <span className="ml-1 text-xs text-muted-foreground">ETF</span> : null}
                  </Link>
                  <span className="shrink-0 text-right tabular-nums">
                    {item.price !== null ? formatPrice(String(item.price)) : "—"}{" "}
                    {item.mark && item.mark.prevClose !== null ? (
                      <PriceChange value={item.mark.price - item.mark.prevClose} className="text-xs" />
                    ) : null}{" "}
                    {item.changePercent !== null ? (
                      <PriceChange value={item.changePercent} suffix="%" className="text-xs" />
                    ) : null}
                  </span>
                </div>
                <div className="flex items-start justify-between gap-2 text-xs text-muted-foreground">
                  <NoteEditor
                    note={item.note}
                    busy={mutate.isPending}
                    onSave={(note) =>
                      mutate.mutate({
                        url: `/api/watchlist/${encodeURIComponent(item.symbol)}`,
                        method: "PATCH",
                        body: { note },
                      })
                    }
                  />
                  <span className="shrink-0">
                    {item.mark?.source === "quote"
                      ? `盤中 ${formatTaipeiDateTime(item.mark.quoteTime).slice(11, 16)}`
                      : item.mark
                        ? `${item.mark.date} 收盤`
                        : "無價格"}
                  </span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`從自選移除 ${item.symbol}`}
                disabled={mutate.isPending}
                onClick={() =>
                  mutate.mutate({ url: `/api/watchlist/${encodeURIComponent(item.symbol)}`, method: "DELETE" })
                }
              >
                <X aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NoteEditor({
  note,
  busy,
  onSave,
}: {
  note: string | null;
  busy: boolean;
  onSave: (note: string | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note ?? "");
  if (!editing) {
    return (
      <button
        type="button"
        className="min-w-0 truncate text-left hover:text-foreground"
        onClick={() => {
          setText(note ?? "");
          setEditing(true);
        }}
      >
        {note ? <span className="text-foreground">{note}</span> : "＋ 備註"}
      </button>
    );
  }
  const save = () => {
    setEditing(false);
    const next = text.trim() || null;
    if (next !== note) onSave(next);
  };
  return (
    <input
      autoFocus
      value={text}
      maxLength={500}
      disabled={busy}
      aria-label="備註"
      onChange={(e) => setText(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") save();
        if (e.key === "Escape") setEditing(false);
      }}
      className="h-7 min-w-0 flex-1 rounded-md border bg-background px-2 text-xs text-foreground"
    />
  );
}
