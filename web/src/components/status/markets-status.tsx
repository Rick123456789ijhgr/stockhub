import Link from "next/link";

import { JobButton } from "@/components/jobs/job-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatInteger } from "@/lib/format";
import type { MarketsStatus } from "@/lib/markets";

/** Market and macro series: latest observation and history per series, quarantine. */
export function MarketsStatusCard({ status }: { status: MarketsStatus }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-sm">市場與總經</CardTitle>
        <CardDescription>
          國際市場、美國利率與總經指標平日 07:30 更新；加權與櫃買指數另在 18:00 隨每日更新抓取。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="text-left font-normal">序列</th>
              <th className="text-right font-normal">最新</th>
              <th className="pl-3 text-right font-normal">筆數</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {status.series.map((s) => (
              <tr key={s.code}>
                <td>{s.name}</td>
                <td className="text-right">
                  {s.lastDate ? (s.frequency === "monthly" ? s.lastDate.slice(0, 7) : s.lastDate) : "—"}
                </td>
                <td className="pl-3 text-right" title={s.firstDate ? `最早 ${s.firstDate}` : undefined}>
                  {formatInteger(s.observations)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {status.quarantinePending > 0 ? (
          <p className="text-sm">
            有 {formatInteger(status.quarantinePending)} 筆市場資料沒通過品質檢查，
            <Link href="/admin?tab=review" className="underline underline-offset-4">
              到設定頁確認
            </Link>
            。
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <JobButton size="xs" variant="outline" label="市場更新到今天" requests={[{ job: "sync_markets" }]} />
          <JobButton size="xs" variant="outline" label="總經指標更新" requests={[{ job: "sync_macro" }]} />
        </div>
      </CardContent>
    </Card>
  );
}
