"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { formatInteger, formatPrice } from "@/lib/format";
import type { FeeSettings } from "@/lib/portfolio";
import type { TransactionRow } from "@/lib/portfolio-data";
import { charges, SIDE_LABEL, type Side } from "@/lib/transaction-input";
import { cn } from "@/lib/utils";

type StockInfo = {
  symbol: string;
  name: string;
  type: "stock" | "etf";
  delistedDate: string | null;
  price: number | null;
  priceDate: string | null;
};

const input =
  "h-9 w-full rounded-md border bg-background px-2 text-sm text-foreground tabular-nums aria-invalid:border-destructive";
const SYMBOL = /^[0-9A-Za-z]{4,6}$/;

function useStockInfo(symbol: string) {
  const s = symbol.trim().toUpperCase();
  return useQuery({
    queryKey: ["stock-info", s],
    enabled: SYMBOL.test(s),
    retry: false,
    staleTime: 60_000,
    queryFn: async (): Promise<StockInfo | null> => {
      const response = await fetch(`/api/stocks/${encodeURIComponent(s)}`);
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (await response.json()) as StockInfo;
    },
  });
}

function amountOrNull(text: string | null): number | null {
  if (text === null || text.trim() === "") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/**
 * Add or edit a trade. Fee, rebate and tax follow the settings and the stock type until
 * typed over ("自動" restores them); the server recomputes the automatic ones.
 */
export function TransactionForm({
  fees,
  today,
  initial,
  onDone,
  onCancel,
}: {
  fees: FeeSettings;
  today: string;
  initial?: TransactionRow;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [symbol, setSymbol] = useState(initial?.symbol ?? "");
  const [tradeDate, setTradeDate] = useState(initial?.tradeDate ?? today);
  const [side, setSide] = useState<Side>(initial?.side ?? "buy");
  const [quantity, setQuantity] = useState(initial ? String(initial.quantity) : "1000");
  const [price, setPrice] = useState(initial ? String(initial.price) : "");
  const [dayTrade, setDayTrade] = useState(initial?.dayTrade ?? false);
  const [note, setNote] = useState(initial?.note ?? "");
  // null = automatic
  const [fee, setFee] = useState<string | null>(initial?.feeManual ? String(initial.fee) : null);
  const [rebate, setRebate] = useState<string | null>(
    initial?.feeManual ? String(initial.feeRebate) : null,
  );
  const [tax, setTax] = useState<string | null>(initial?.taxManual ? String(initial.tax) : null);

  const info = useStockInfo(symbol);
  const stock = info.data ?? null;
  const qty = Number(quantity);
  const px = Number(price);
  const valid = Number.isInteger(qty) && qty > 0 && Number.isFinite(px) && px > 0;
  const auto = valid
    ? charges(
        {
          side,
          quantity: qty,
          price: px,
          tradeDate,
          dayTrade,
          fee: amountOrNull(fee),
          feeRebate: amountOrNull(rebate),
          tax: amountOrNull(tax),
        },
        { type: stock?.type ?? "stock", symbol: stock?.symbol ?? symbol },
        fees,
      )
    : null;
  const amount = valid ? qty * px : null;
  const net =
    amount !== null && auto
      ? side === "buy"
        ? amount + auto.fee
        : amount - auto.fee - auto.tax
      : null;

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        symbol,
        tradeDate,
        side,
        quantity,
        price,
        dayTrade,
        note,
        fee: fee === null || fee.trim() === "" ? null : fee,
        feeRebate: fee === null ? null : (rebate ?? "0"),
        tax: tax === null || tax.trim() === "" ? null : tax,
      };
      const response = await fetch(
        initial ? `/api/portfolio/transactions/${initial.id}` : "/api/portfolio/transactions",
        {
          method: initial ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `HTTP ${response.status}`);
      }
    },
    onSuccess: onDone,
  });

  return (
    <form
      className="space-y-3 rounded-lg border p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{initial ? "修改交易" : "新增交易"}</h3>
        <div role="radiogroup" aria-label="買賣" className="inline-flex rounded-md border p-0.5">
          {(["buy", "sell"] as const).map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={side === s}
              onClick={() => setSide(s)}
              className={cn(
                "rounded px-3 py-1 text-sm",
                side === s && (s === "buy" ? "bg-up/15 text-up" : "bg-down/15 text-down"),
              )}
            >
              {SIDE_LABEL[s]}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="grid content-start gap-1 text-xs text-muted-foreground">
          代號
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            autoCapitalize="characters"
            autoComplete="off"
            required
            aria-invalid={info.data === null}
            className={input}
          />
          <span className="min-h-4 truncate text-foreground">
            {stock ? `${stock.name}${stock.type === "etf" ? "（ETF）" : ""}` : null}
            {info.data === null ? <span className="text-destructive">找不到這個代號</span> : null}
          </span>
        </label>
        <label className="grid content-start gap-1 text-xs text-muted-foreground">
          成交日
          <input
            type="date"
            value={tradeDate}
            max={today}
            onChange={(e) => setTradeDate(e.target.value)}
            required
            className={input}
          />
        </label>
        <label className="grid content-start gap-1 text-xs text-muted-foreground">
          股數
          <input
            inputMode="numeric"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
            className={input}
          />
          <span className="min-h-4">
            {Number.isInteger(qty) && qty > 0
              ? qty % 1000 === 0
                ? `${formatInteger(qty / 1000)} 張`
                : qty < 1000
                  ? "零股"
                  : `${formatInteger(Math.floor(qty / 1000))} 張又 ${qty % 1000} 股`
              : null}
          </span>
        </label>
        <label className="grid content-start gap-1 text-xs text-muted-foreground">
          成交價
          <input
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
            className={input}
          />
          <span className="min-h-4">
            {stock?.price != null ? (
              <button
                type="button"
                className="underline-offset-2 hover:underline"
                onClick={() => setPrice(String(stock.price))}
              >
                最近 {formatPrice(String(stock.price))}（{stock.priceDate}）
              </button>
            ) : null}
          </span>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <ChargeField
          label="手續費"
          value={fee}
          auto={auto && fee === null ? auto.fee : null}
          onChange={(v) => {
            setFee(v);
            if (v === null) setRebate(null);
            else if (rebate === null) setRebate("0");
          }}
        />
        {fees.discountMode === "rebate" || (fee !== null && rebate !== "0") ? (
          <ChargeField
            label="事後退佣（估）"
            value={fee === null ? null : rebate}
            auto={auto && fee === null ? auto.feeRebate : null}
            onChange={(v) => {
              if (fee === null && v !== null) setFee(String(auto?.fee ?? 0));
              setRebate(v ?? (fee === null ? null : "0"));
            }}
          />
        ) : null}
        {side === "sell" ? (
          <ChargeField
            label="證交稅"
            value={tax}
            auto={auto && tax === null ? auto.tax : null}
            onChange={setTax}
          />
        ) : null}
        <label className="flex h-9 items-center gap-2 self-end text-sm">
          <input type="checkbox" checked={dayTrade} onChange={(e) => setDayTrade(e.target.checked)} />
          當沖
        </label>
      </div>

      <label className="grid content-start gap-1 text-xs text-muted-foreground">
        備註
        <input value={note} onChange={(e) => setNote(e.target.value)} className={input} />
      </label>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground tabular-nums">
          {amount !== null && net !== null
            ? `成交金額 ${formatInteger(Math.round(amount))} 元，${side === "buy" ? "應付" : "應收"} ${formatInteger(Math.round(net))} 元`
            : "輸入股數與成交價後試算金額"}
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button type="submit" disabled={!valid || save.isPending || info.data === null}>
            {initial ? "儲存" : "新增"}
          </Button>
        </div>
      </div>
      {save.isError ? <p className="text-xs text-destructive">{save.error.message}</p> : null}
    </form>
  );
}

function ChargeField({
  label,
  value,
  auto,
  onChange,
}: {
  label: string;
  value: string | null;
  auto: number | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <label className="grid content-start gap-1 text-xs text-muted-foreground">
      <span className="flex items-center justify-between gap-1">
        {label}
        {value === null ? (
          <span className="rounded bg-muted px-1">自動</span>
        ) : (
          <button type="button" className="underline-offset-2 hover:underline" onClick={() => onChange(null)}>
            改回自動
          </button>
        )}
      </span>
      <input
        inputMode="decimal"
        value={value ?? (auto === null ? "" : String(auto))}
        onChange={(e) => onChange(e.target.value)}
        className={cn(input, value === null && "text-muted-foreground")}
      />
    </label>
  );
}
