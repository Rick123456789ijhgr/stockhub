"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { QuarantinedStatement } from "@/lib/fundamentals-status";

const STATEMENT = { IS: "損益表", BS: "資產負債表", CF: "現金流量表" } as const;
const REASON: Record<string, string> = {
  ytd_as_quarter: "單季營收等於年初至今月營收合計（疑似把累計數當單季）",
  unbalanced: "資產 ≠ 負債 + 權益",
  liabilities_inconsistent:
    "資產與權益各自加總正確，但負債數字對不上（其他科目已寫入；負債比率暫用資產 − 權益）",
  non_positive_assets: "資產總額不是正數",
  negative_revenue: "營收為負",
};
const SHOWN_ITEMS = [
  "Revenue",
  "GrossProfit",
  "OperatingIncome",
  "NetIncomeParent",
  "EPS",
  "TotalAssets",
  "TotalLiabilities",
  "CurrentLiabilities",
  "NoncurrentLiabilities",
  "TotalEquity",
];

export function FinancialsQuarantineList({ rows }: { rows: QuarantinedStatement[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">沒有待確認的財報。</p>;
  }
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <Item key={row.id} row={row} />
      ))}
    </ul>
  );
}

function Item({ row }: { row: QuarantinedStatement }) {
  const router = useRouter();
  const resolve = useMutation({
    mutationFn: async (decision: "accept" | "reject") => {
      const response = await fetch(`/api/admin/financials-quarantine/${row.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => router.refresh(),
  });
  const items = row.items.filter((i) => SHOWN_ITEMS.includes(i.itemCode));
  return (
    <li className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link href={`/stocks/${row.symbol}`} className="font-medium hover:underline">
          {row.symbol} {row.name}
        </Link>
        <span className="tabular-nums">{row.periodEnd}</span>
        <span>{STATEMENT[row.statement]}</span>
        <Badge variant="outline">{row.source}</Badge>
      </div>
      <ul className="list-disc pl-5 text-muted-foreground">
        {row.reasons.map((r) => (
          <li key={r}>{REASON[r] ?? r}</li>
        ))}
      </ul>
      {items.length > 0 ? (
        <p className="text-xs text-muted-foreground tabular-nums">
          {items.map((i) => `${i.itemCode} ${Number(i.value).toLocaleString("zh-TW")}`).join("　")}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={resolve.isPending} onClick={() => resolve.mutate("reject")}>
          捨棄
        </Button>
        <Button size="sm" variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate("accept")}>
          仍然採用
        </Button>
        {resolve.isError ? <span className="text-xs text-destructive">送出失敗</span> : null}
      </div>
    </li>
  );
}
