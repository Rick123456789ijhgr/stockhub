import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { periodLabel } from "@/lib/chart-format";
import { formatInteger } from "@/lib/format";
import type { FundamentalsStatus } from "@/lib/fundamentals-status";

function eta(startedAt: string, done: number, total: number, now: Date): string {
  if (done === 0 || total === 0) return "計算中";
  const elapsed = (now.getTime() - new Date(startedAt).getTime()) / 1000;
  const remaining = (elapsed / done) * (total - done);
  if (remaining < 3600) return `約 ${Math.max(1, Math.round(remaining / 60))} 分鐘`;
  return `約 ${(remaining / 3600).toFixed(1)} 小時`;
}

/** Statement and revenue coverage, the running history backfill, pending quarantine. */
export function FundamentalsStatusCard({ status, now }: { status: FundamentalsStatus; now: Date }) {
  const run = status.backfill;
  const tiles = [
    { label: "財報（已抓歷史）", value: `${formatInteger(status.statementsFetched)}／${formatInteger(status.companies)} 家` },
    { label: "月營收（已抓歷史）", value: `${formatInteger(status.revenueFetched)}／${formatInteger(status.companies)} 家` },
    {
      label: "最新一季（官方）",
      value: status.latestQuarter
        ? `${periodLabel(status.latestQuarter, "quarter")}（${formatInteger(status.latestQuarterCompanies)} 家）`
        : "尚無",
    },
    {
      label: "最新月營收",
      value: status.latestRevenueMonth
        ? `${periodLabel(status.latestRevenueMonth, "month")}（${formatInteger(status.latestRevenueCompanies)} 家）`
        : "尚無",
    },
    { label: "已計算基本面", value: `${formatInteger(status.computed)} 家` },
  ];
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-sm">財報與月營收</CardTitle>
        <CardDescription>
          歷史來自 FinMind（每小時最多 500 次請求）；每天傍晚用證交所與櫃買的 OpenAPI 更新最新一季與月營收。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          {tiles.map((t) => (
            <div key={t.label}>
              <dt className="text-xs text-muted-foreground">{t.label}</dt>
              <dd className="tabular-nums">{t.value}</dd>
            </div>
          ))}
        </dl>
        {run ? (
          <div className="space-y-1 text-sm">
            <p>
              歷史回填進行中（任務 #{run.id}）：{formatInteger(run.done)}／{formatInteger(run.total)} 家
              {run.symbol ? `，目前 ${run.symbol}` : ""}，剩餘{eta(run.startedAt, run.done, run.total, now)}
            </p>
            <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div
                className="h-full rounded-full bg-series-1"
                style={{ width: `${run.total ? (run.done / run.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ) : null}
        {status.quarantinePending > 0 ? (
          <p className="text-sm">
            有 {formatInteger(status.quarantinePending)} 份財報沒通過品質檢查，
            <Link href="/admin?tab=review" className="underline underline-offset-4">
              到設定頁確認
            </Link>
            。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
