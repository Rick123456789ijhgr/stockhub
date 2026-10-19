"use client";

import { useMutation } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { TransactionForm } from "@/components/portfolio/transaction-form";
import { Button } from "@/components/ui/button";
import { formatInteger, formatPrice } from "@/lib/format";
import type { FeeSettings } from "@/lib/portfolio";
import type { TransactionRow } from "@/lib/portfolio-data";
import { SIDE_LABEL } from "@/lib/transaction-input";
import { cn } from "@/lib/utils";

/** Trade ledger with inline add / edit forms; `#add` in the URL opens the add form. */
export function TransactionsPanel({
  transactions,
  total,
  fees,
  today,
}: {
  /** The newest ones (all when the page asks for all). */
  transactions: TransactionRow[];
  total: number;
  fees: FeeSettings;
  today: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState<string | "new" | null>(
    transactions.length === 0 ? "new" : null,
  );
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const open = () => {
      if (window.location.hash === "#add") {
        setEditing("new");
        ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    open();
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, []);

  const remove = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetch(`/api/portfolio/transactions/${id}`, { method: "DELETE" });
      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `HTTP ${response.status}`);
      }
    },
    onSuccess: () => router.refresh(),
  });

  const done = () => {
    setEditing(null);
    if (window.location.hash === "#add") history.replaceState(null, "", window.location.pathname);
    router.refresh();
  };

  return (
    <div ref={ref} className="scroll-mt-4 space-y-3">
      {editing === "new" ? (
        <TransactionForm fees={fees} today={today} onDone={done} onCancel={() => setEditing(null)} />
      ) : (
        <Button variant="outline" onClick={() => setEditing("new")}>
          <Plus aria-hidden />
          新增交易
        </Button>
      )}
      {remove.isError ? <p className="text-xs text-destructive">{remove.error.message}</p> : null}
      {transactions.length === 0 ? (
        <p className="text-sm text-muted-foreground">還沒有交易紀錄。</p>
      ) : (
        <ul className="divide-y text-sm">
          {transactions.map((t) =>
            editing === t.id ? (
              <li key={t.id} className="py-2">
                <TransactionForm
                  fees={fees}
                  today={today}
                  initial={t}
                  onDone={done}
                  onCancel={() => setEditing(null)}
                />
              </li>
            ) : (
              <TransactionItem
                key={t.id}
                t={t}
                busy={remove.isPending}
                onEdit={() => setEditing(t.id)}
                onDelete={() => {
                  if (window.confirm(`刪除 ${t.tradeDate} ${SIDE_LABEL[t.side]} ${t.symbol} ${formatInteger(t.quantity)} 股？`)) {
                    remove.mutate(t.id);
                  }
                }}
              />
            ),
          )}
        </ul>
      )}
      <ShowAll shown={transactions.length} total={total} anchor="transactions" />
    </div>
  );
}

/** "顯示全部 N 筆" for lists the server cut to their newest entries. */
export function ShowAll({ shown, total, anchor }: { shown: number; total: number; anchor: string }) {
  if (shown >= total) return null;
  return (
    <Link href={`/portfolio?all=1#${anchor}`} className="inline-block text-sm text-muted-foreground underline-offset-2 hover:underline">
      只顯示最近 {formatInteger(shown)} 筆，顯示全部 {formatInteger(total)} 筆
    </Link>
  );
}

function TransactionItem({
  t,
  busy,
  onEdit,
  onDelete,
}: {
  t: TransactionRow;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const amount = t.quantity * t.price;
  const net = t.side === "buy" ? -(amount + t.fee) : amount - t.fee - t.tax;
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0 space-y-0.5">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-xs text-muted-foreground tabular-nums">{t.tradeDate}</span>
          <span
            className={cn(
              "rounded px-1.5 text-xs",
              t.side === "buy" ? "bg-up/15 text-up" : "bg-down/15 text-down",
            )}
          >
            {SIDE_LABEL[t.side]}
          </span>
          <Link href={`/stocks/${t.symbol}`} className="font-medium hover:underline">
            {t.symbol} {t.name}
          </Link>
          {t.dayTrade ? <span className="text-xs text-muted-foreground">當沖</span> : null}
        </div>
        <div className="text-xs text-muted-foreground tabular-nums">
          {formatInteger(t.quantity)} 股 × {formatPrice(String(t.price))}
          ，手續費 {formatInteger(t.fee)}
          {t.feeManual ? "（手動）" : ""}
          {t.feeRebate > 0 ? `，退佣 ${formatInteger(t.feeRebate)}` : ""}
          {t.side === "sell" ? `，證交稅 ${formatInteger(t.tax)}${t.taxManual ? "（手動）" : ""}` : ""}
          ，{net < 0 ? "付" : "收"} {formatInteger(Math.round(Math.abs(net)))} 元
        </div>
        {t.note ? <div className="text-xs">{t.note}</div> : null}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button variant="ghost" size="icon-sm" aria-label="修改" onClick={onEdit}>
          <Pencil aria-hidden />
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="刪除" disabled={busy} onClick={onDelete}>
          <Trash2 aria-hidden />
        </Button>
      </div>
    </li>
  );
}
