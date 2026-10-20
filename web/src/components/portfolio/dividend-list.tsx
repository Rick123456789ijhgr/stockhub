"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ACTION_LABEL, ratioText, StockName } from "@/components/portfolio/holdings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatInteger } from "@/lib/format";
import { type DividendEntry, receiptKey } from "@/lib/portfolio";
import type { ReceiptDetail, StockRef } from "@/lib/portfolio-data";

const input =
  "h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground tabular-nums";

/** Dividends and share changes, newest first; each can be reconciled with what arrived. */
export function DividendList({
  dividends,
  stocks,
  receipts,
}: {
  dividends: DividendEntry[];
  stocks: Record<string, StockRef>;
  receipts: Record<string, ReceiptDetail>;
}) {
  if (dividends.length === 0) {
    return <p className="text-sm text-muted-foreground">持有期間沒有除權息或股數變動。</p>;
  }
  const sorted = [...dividends].sort((a, b) =>
    a.exDate < b.exDate ? 1 : a.exDate > b.exDate ? -1 : 0,
  );
  return (
    <ul className="divide-y text-sm">
      {sorted.map((d) => {
        const key = receiptKey(d.stock, d.exDate, d.actionType);
        return (
          <DividendItem key={key} d={d} stock={stocks[d.stock]} receipt={receipts[key] ?? null} />
        );
      })}
    </ul>
  );
}

function DividendItem({
  d,
  stock,
  receipt,
}: {
  d: DividendEntry;
  stock: StockRef | undefined;
  receipt: ReceiptDetail | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const pays = d.estCash > 0 || d.estStockShares > 0;
  const shareChange = d.sharesAfter - d.sharesHeld - d.stockShares;
  const cashLabel = d.actionType === "capital_reduction" ? "退還股款" : "現金股利";

  const clear = useMutation({
    mutationFn: async () => {
      const params = new URLSearchParams({
        symbol: stock?.symbol ?? "",
        exDate: d.exDate,
        actionType: d.actionType,
      });
      const response = await fetch(`/api/portfolio/dividends?${params}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => router.refresh(),
  });

  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-xs text-muted-foreground tabular-nums">{d.exDate}</span>
        <span className="text-xs">{ACTION_LABEL[d.actionType] ?? d.actionType}</span>
        <StockName stock={stock} />
        {d.received ? <Badge>已對帳</Badge> : <Badge variant="outline">估算</Badge>}
        {d.implied ? <Badge variant="secondary">比例由參考價推算</Badge> : null}
      </div>
      <div className="text-xs text-muted-foreground tabular-nums">
        除權息前持有 {formatInteger(d.sharesHeld)} 股
        {d.estCash > 0
          ? `，每股 ${ratioText(d.cashPerShare)} 元，${cashLabel}${d.received ? "估算" : ""} ${formatInteger(d.estCash)} 元`
          : ""}
        {d.estStockShares > 0
          ? `，配股 ${ratioText(d.stockRatio * 1000)}‰ ≈ ${formatInteger(d.estStockShares)} 股`
          : ""}
        {shareChange !== 0
          ? `，股數 × ${ratioText(d.shareRatio)}（${shareChange > 0 ? "+" : ""}${formatInteger(shareChange)} 股）`
          : ""}
        ，之後 {formatInteger(d.sharesAfter)} 股
        {!d.received && d.nhi > 0 ? `；補充保費約 ${formatInteger(d.nhi)} 元另扣` : ""}
      </div>
      {d.received && receipt ? (
        <div className="text-xs tabular-nums">
          實收
          {receipt.cash !== null ? ` 現金 ${formatInteger(receipt.cash)} 元` : ""}
          {receipt.shares !== null ? ` 股票 ${formatInteger(receipt.shares)} 股` : ""}
          {receipt.cash !== null && d.estCash > 0 ? (
            <span className="text-muted-foreground">
              （與估算差 {formatInteger(Math.round(receipt.cash - d.estCash))} 元）
            </span>
          ) : null}
          {receipt.payDate ? `，${receipt.payDate} 入帳` : ""}
          {receipt.note ? `，${receipt.note}` : ""}
        </div>
      ) : null}
      {pays && !editing ? (
        <div className="flex gap-2">
          <Button variant="ghost" size="xs" onClick={() => setEditing(true)}>
            {d.received ? "修改實收" : "輸入實收"}
          </Button>
          {d.received ? (
            <Button variant="ghost" size="xs" disabled={clear.isPending} onClick={() => clear.mutate()}>
              改回估算
            </Button>
          ) : null}
        </div>
      ) : null}
      {editing ? (
        <ReceiptForm
          d={d}
          symbol={stock?.symbol ?? ""}
          receipt={receipt}
          onDone={() => {
            setEditing(false);
            router.refresh();
          }}
          onCancel={() => setEditing(false)}
        />
      ) : null}
    </li>
  );
}

function ReceiptForm({
  d,
  symbol,
  receipt,
  onDone,
  onCancel,
}: {
  d: DividendEntry;
  symbol: string;
  receipt: ReceiptDetail | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const suggested = d.estCash - d.nhi;
  const [cash, setCash] = useState(
    receipt?.cash != null ? String(receipt.cash) : d.estCash > 0 ? String(suggested) : "",
  );
  const [shares, setShares] = useState(
    receipt?.shares != null ? String(receipt.shares) : d.estStockShares > 0 ? String(d.estStockShares) : "",
  );
  const [payDate, setPayDate] = useState(receipt?.payDate ?? "");
  const [note, setNote] = useState(receipt?.note ?? "");
  const save = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/portfolio/dividends", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          exDate: d.exDate,
          actionType: d.actionType,
          cash,
          shares,
          payDate,
          note,
        }),
      });
      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `HTTP ${response.status}`);
      }
    },
    onSuccess: onDone,
  });
  return (
    <form
      className="grid grid-cols-2 gap-2 rounded-md border p-2 sm:grid-cols-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="grid content-start gap-1 text-xs text-muted-foreground">
        實收現金（元）
        <input inputMode="decimal" value={cash} onChange={(e) => setCash(e.target.value)} className={input} />
      </label>
      {d.estStockShares > 0 ? (
        <label className="grid content-start gap-1 text-xs text-muted-foreground">
          實收股數
          <input inputMode="numeric" value={shares} onChange={(e) => setShares(e.target.value)} className={input} />
        </label>
      ) : null}
      <label className="grid content-start gap-1 text-xs text-muted-foreground">
        入帳日
        <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className={input} />
      </label>
      <label className="col-span-2 grid gap-1 text-xs text-muted-foreground sm:col-span-1">
        備註
        <input value={note} onChange={(e) => setNote(e.target.value)} className={input} />
      </label>
      <div className="col-span-2 flex items-end gap-2 sm:col-span-1">
        <Button type="submit" size="sm" disabled={save.isPending}>
          儲存
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>
          取消
        </Button>
      </div>
      <p className="col-span-2 text-xs text-muted-foreground sm:col-span-5">
        填入帳通知上的淨額（已扣匯費與補充保費）；預設值是估算減去補充保費。空白表示沿用估算。
      </p>
      {save.isError ? (
        <p className="col-span-2 text-xs text-destructive sm:col-span-5">{save.error.message}</p>
      ) : null}
    </form>
  );
}
