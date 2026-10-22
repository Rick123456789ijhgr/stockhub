"use client";

import { useMutation } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { DISCLOSURE_CHEVRON } from "@/components/disclosure";
import { ShowMoreList } from "@/components/show-more";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { sendJson } from "@/lib/send-json";
import type { QuarantinedObservation } from "@/lib/series-quarantine";

const REASON: Record<string, string> = {
  ohlc_inconsistent: "開盤或收盤不在最高與最低之間",
  not_positive: "數值不是正數",
  move_too_large: "和前一筆相比變動超過門檻",
};
const SHOWN = 20;

export function SeriesQuarantineList({ rows }: { rows: QuarantinedObservation[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">沒有待確認的市場資料。</p>;
  return (
    <ShowMoreList
      className="divide-y"
      initial={SHOWN}
      step={SHOWN}
      items={rows.map((row) => (
        <Item key={row.id} row={row} />
      ))}
    />
  );
}

function Item({ row }: { row: QuarantinedObservation }) {
  const router = useRouter();
  const resolve = useMutation({
    mutationFn: (decision: "accept" | "reject") =>
      sendJson("POST", `/api/admin/series-quarantine/${row.id}`, { decision }),
    onSuccess: () => router.refresh(),
  });
  const value = (row.payload as { value?: string } | null)?.value;
  return (
    <li className="py-1.5 text-sm">
      <details>
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
          <ChevronRight className={DISCLOSURE_CHEVRON} aria-hidden />
          <span className="font-medium">{row.name}</span>
          <span className="tabular-nums">{row.obsDate}</span>
          <span className="text-muted-foreground tabular-nums">
            {value ?? "—"}
            {row.previous !== null ? `（前一筆 ${row.previous}）` : ""}
          </span>
          <Badge variant="outline">{row.source}</Badge>
          <div className="ml-auto flex items-center gap-1.5">
            {resolve.error ? <span className="text-xs text-destructive">{resolve.error.message}</span> : null}
            <Button
              size="sm"
              variant="outline"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("reject")}
            >
              捨棄
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("accept")}
            >
              仍然採用
            </Button>
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
