import Link from "next/link";

import { JobButton } from "@/components/jobs/job-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ChipsStatus } from "@/lib/chips";
import { formatInteger } from "@/lib/format";

const DATASET_LABEL: Record<string, string> = {
  institutional: "三大法人",
  margin: "融資融券",
  foreign_holdings: "外資持股",
  market_institutional: "法人金額（全市場）",
  distribution: "集保股權分散（週）",
};
const MARKET_LABEL: Record<string, string> = { twse: "上市", tpex: "上櫃", all: "" };

function eta(startedAt: string, done: number, total: number, now: Date): string {
  if (done === 0 || total === 0) return "計算中";
  const elapsed = (now.getTime() - new Date(startedAt).getTime()) / 1000;
  const remaining = (elapsed / done) * (total - done);
  if (remaining < 3600) return `約 ${Math.max(1, Math.round(remaining / 60))} 分鐘`;
  return `約 ${(remaining / 3600).toFixed(1)} 小時`;
}

/** Chip tables per dataset and market (chip_coverage), the history backfill, quarantine. */
export function ChipsStatusCard({ status, now }: { status: ChipsStatus; now: Date }) {
  const run = status.backfill;
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-base">籌碼</CardTitle>
        <CardDescription>
          證交所、櫃買中心每日公告（18:00 與 21:30 各抓一次，融資融券晚上才公布），集保每週一次。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {status.coverage.length === 0 ? (
          <p className="text-sm text-muted-foreground">還沒有籌碼資料。</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr>
                <th className="text-left font-normal">資料</th>
                <th className="text-right font-normal">最新</th>
                <th className="pl-3 text-right font-normal">天數</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {status.coverage.map((c) => (
                <tr key={`${c.dataset}-${c.market}`}>
                  <td>
                    {DATASET_LABEL[c.dataset] ?? c.dataset} {MARKET_LABEL[c.market] ?? c.market}
                  </td>
                  <td className="text-right">{c.last ?? "—"}</td>
                  <td className="pl-3 text-right" title={c.first ? `最早 ${c.first}` : undefined}>
                    {formatInteger(c.days)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-muted-foreground">已計算籌碼摘要 {formatInteger(status.summaries)} 檔</p>
        {run ? (
          <div className="space-y-1 text-sm">
            <p>
              歷史回填進行中（任務 #{run.id}）：{formatInteger(run.done)}／{formatInteger(run.total)} 個交易日
              {run.next ? `，目前 ${run.next}` : ""}，剩餘{eta(run.startedAt, run.done, run.total, now)}
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
            有 {formatInteger(status.quarantinePending)} 筆籌碼沒通過品質檢查，
            <Link href="/admin?tab=review" className="underline underline-offset-4">
              到設定頁確認
            </Link>
            。
          </p>
        ) : null}
        <JobButton size="xs" variant="outline" label="籌碼更新到今天" requests={[{ job: "sync_chips" }]} />
      </CardContent>
    </Card>
  );
}
