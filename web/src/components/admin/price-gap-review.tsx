"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  describeShareRatio,
  GAP_ACTION_LABEL,
  GAP_ACTION_TYPES,
  type GapActionType,
} from "@/lib/price-gap-decision";
import type { PriceGap } from "@/lib/price-gaps";

type Body =
  | { decision: "confirm"; ratio: string; actionType: GapActionType }
  | { decision: "dismiss" };

/** One card per pending gap: confirm the suggested (or an edited) ratio, or dismiss it. */
export function PriceGapList({ gaps }: { gaps: PriceGap[] }) {
  if (gaps.length === 0) {
    return <p className="text-sm text-muted-foreground">沒有待確認的價格跳空。</p>;
  }
  return (
    <ul className="space-y-3">
      {gaps.map((gap) => (
        <PriceGapItem key={gap.id} gap={gap} />
      ))}
    </ul>
  );
}

function PriceGapItem({ gap }: { gap: PriceGap }) {
  const router = useRouter();
  const fallbackRatio = gap.priceRatio > 0 ? 1 / gap.priceRatio : 1;
  const [ratio, setRatio] = useState(
    String(gap.suggestion?.ratio ?? Number(fallbackRatio.toFixed(4))),
  );
  const [actionType, setActionType] = useState<GapActionType>(
    gap.suggestion?.actionType ?? (gap.priceRatio < 1 ? "split" : "capital_reduction"),
  );
  const resolve = useMutation({
    mutationFn: async (body: Body) => {
      const response = await fetch(`/api/admin/price-gaps/${gap.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => router.refresh(),
  });
  const parsed = Number(ratio);
  const valid = Number.isFinite(parsed) && parsed >= 0.02 && parsed <= 50 && parsed !== 1;
  const move = (gap.priceRatio - 1) * 100;

  return (
    <li className="space-y-3 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link href={`/stocks/${gap.symbol}`} className="font-medium hover:underline">
          {gap.symbol} {gap.name ?? ""}
        </Link>
        <span className="text-muted-foreground">
          {gap.market === "tpex" ? "上櫃" : gap.market === "twse" ? "上市" : ""}
        </span>
        <span className="tabular-nums">{gap.exDate}</span>
        {gap.suggestion ? (
          <Badge variant="secondary">
            疑似{GAP_ACTION_LABEL[gap.suggestion.actionType]}：
            {describeShareRatio(gap.suggestion.ratio)}
          </Badge>
        ) : (
          <Badge variant="outline">無法對應常見比例</Badge>
        )}
      </div>
      <p className="text-muted-foreground tabular-nums">
        還原收盤 {gap.previousClose.toFixed(2)}（{gap.previousDate}）→ {gap.close.toFixed(2)}
        ，變動 {move >= 0 ? "+" : ""}
        {move.toFixed(1)}%
        {gap.suggestion
          ? `；扣除事件後當日漲跌 ${gap.suggestion.impliedMove >= 0 ? "+" : ""}${(gap.suggestion.impliedMove * 100).toFixed(1)}%`
          : null}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-xs text-muted-foreground">
          股數比（後 ÷ 前）
          <input
            inputMode="decimal"
            value={ratio}
            onChange={(e) => setRatio(e.target.value)}
            aria-invalid={!valid}
            className="h-8 w-24 rounded-md border bg-background px-2 text-sm text-foreground tabular-nums aria-invalid:border-destructive"
          />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          事件類型
          <select
            value={actionType}
            onChange={(e) => setActionType(e.target.value as GapActionType)}
            className="h-8 rounded-md border bg-background px-2 text-sm text-foreground"
          >
            {GAP_ACTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {GAP_ACTION_LABEL[t]}
              </option>
            ))}
          </select>
        </label>
        <Button
          disabled={!valid || resolve.isPending}
          onClick={() => resolve.mutate({ decision: "confirm", ratio, actionType })}
        >
          確認事件
        </Button>
        <Button
          variant="outline"
          disabled={resolve.isPending}
          onClick={() => resolve.mutate({ decision: "dismiss" })}
        >
          不是事件
        </Button>
      </div>
      {valid ? (
        <p className="text-xs text-muted-foreground">
          確認後記為：{describeShareRatio(parsed)}，{gap.exDate} 之前的價格乘以{" "}
          {Number((1 / parsed).toFixed(6))}。
        </p>
      ) : (
        <p className="text-xs text-destructive">股數比需介於 0.02 與 50 之間，且不等於 1。</p>
      )}
      {resolve.isError ? (
        <p className="text-xs text-destructive">儲存失敗，請重新整理後再試。</p>
      ) : null}
    </li>
  );
}
