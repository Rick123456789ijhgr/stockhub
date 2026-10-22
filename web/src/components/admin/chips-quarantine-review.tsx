"use client";

import { useMutation } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { DISCLOSURE_CHEVRON } from "@/components/disclosure";
import { ShowMoreList } from "@/components/show-more";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { sendJson } from "@/lib/send-json";
import type { ChipDataset, QuarantinedChip } from "@/lib/chips-quarantine";

const DATASET: Record<ChipDataset, string> = {
  institutional: "三大法人",
  margin: "融資融券",
  foreign_holdings: "外資持股",
  distribution: "集保股權分散",
};
const REASON: Record<string, string> = {
  total_mismatch: "外資 + 投信 + 自營商 ≠ 三大法人合計",
  foreign_net_mismatch: "外資買進 − 賣出 ≠ 買賣超",
  trust_net_mismatch: "投信買進 − 賣出 ≠ 買賣超",
  dealer_net_mismatch: "自營商買進 − 賣出 ≠ 買賣超",
  foreign_dealer_net_mismatch: "外資自營商買進 − 賣出 ≠ 買賣超",
  dealer_parts_mismatch: "自營商自行買賣 + 避險 ≠ 自營商合計",
  margin_balance_mismatch: "融資前日餘額 + 買進 − 賣出 − 現償 ≠ 今日餘額",
  short_balance_mismatch: "融券前日餘額 + 賣出 − 買進 − 現券償還 ≠ 今日餘額",
  ratio_out_of_range: "外資持股比不在 0～100%",
  limit_out_of_range: "投資上限不在 0～100%",
  ratio_mismatch: "外資持股比 ≠ 持有股數 ÷ 發行股數",
  levels_do_not_add_up: "各級距股數加總對不上合計",
  missing_total: "缺合計列",
};
/** Rows failing these cannot be stored at all (the table's CHECK holds ratios to 0–1). */
const REJECT_ONLY = new Set(["ratio_out_of_range", "limit_out_of_range"]);
const SHOWN = 20;

export function ChipsQuarantineList({ rows }: { rows: QuarantinedChip[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">沒有待確認的籌碼資料。</p>;
  return (
    <ShowMoreList className="divide-y" initial={SHOWN} step={SHOWN} items={rows.map((row) => <Item key={row.id} row={row} />)} />
  );
}

function Item({ row }: { row: QuarantinedChip }) {
  const router = useRouter();
  const resolve = useMutation({
    mutationFn: (decision: "accept" | "reject") =>
      sendJson("POST", `/api/admin/chips-quarantine/${row.id}`, { decision }),
    onSuccess: () => router.refresh(),
  });
  return (
    <li className="py-1.5 text-sm">
      <details>
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
          <ChevronRight className={DISCLOSURE_CHEVRON} aria-hidden />
          <Link href={`/stocks/${row.symbol}?tab=chips`} className="font-medium hover:underline">
            {row.symbol} {row.name}
          </Link>
          <span className="tabular-nums">{row.tradeDate}</span>
          <span>{DATASET[row.dataset]}</span>
          <Badge variant="outline">{row.source}</Badge>
          <div className="ml-auto flex items-center gap-1.5">
            {resolve.error ? <span className="text-xs text-destructive">{resolve.error.message}</span> : null}
            <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate("reject")}>
              捨棄
            </Button>
            {row.reasons.some((r) => REJECT_ONLY.has(r)) ? (
              <span className="text-xs text-muted-foreground" title="比率超出 0～100%，資料表不能儲存">
                只能捨棄
              </span>
            ) : (
              <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate("accept")}>
                仍然採用
              </Button>
            )}
          </div>
        </summary>
        <div className="space-y-1 pt-1 pl-7 text-xs text-muted-foreground">
          <ul className="list-disc pl-4">
            {row.reasons.map((r) => (
              <li key={r}>{REASON[r] ?? r}</li>
            ))}
          </ul>
          <pre className="overflow-x-auto rounded bg-muted p-2 text-[11px] leading-snug">
            {JSON.stringify(row.payload, null, 1)}
          </pre>
        </div>
      </details>
    </li>
  );
}
