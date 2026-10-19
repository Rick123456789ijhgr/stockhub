import type { Metadata } from "next";
import { Suspense } from "react";

import { PriceGapList } from "@/components/admin/price-gap-review";
import { AppearanceSettings } from "@/components/appearance-controls";
import { PageHeader } from "@/components/coming-soon";
import { PriceChange } from "@/components/price-change";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { formatInteger } from "@/lib/format";
import { countPendingGaps, listPendingGaps } from "@/lib/price-gaps";

export const metadata: Metadata = { title: "設定" };

const PLANNED = [
  { name: "自選清單、手續費設定", milestone: "M2" },
  { name: "題材編輯", milestone: "M5" },
  { name: "警示規則", milestone: "M6" },
  { name: "排程管理", milestone: "M1 起" },
  { name: "稽核紀錄（讀取函式已備妥：lib/audit.ts）", milestone: "M2 起" },
];

export default function AdminPage() {
  return (
    <>
      <PageHeader title="設定" description="資料確認與顯示設定；手動操作都會寫入稽核紀錄。" />
      <div className="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">待確認的價格跳空</CardTitle>
            <CardDescription>
              還原價相鄰兩日變動超出 −40%～+50%，而且沒有任何已知事件可以解釋（多半是櫃買的面額變更、ETF
              分割或早年減資）。確認後記為手動事件；之後若匯入官方事件，會自動取代手動紀錄。還原價在下次執行{" "}
              <code>compute_adj_factors</code>（<code>make etl-daily</code> 或{" "}
              <code>make etl-adjust</code>）時更新。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <PriceGaps />
            </Suspense>
          </CardContent>
        </Card>
        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">顯示</CardTitle>
              <CardDescription>深色模式與漲跌配色；圖表會跟著切換。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <AppearanceSettings />
              <div className="flex gap-4 text-sm">
                <PriceChange value={1.25} suffix="%" />
                <PriceChange value={-0.8} suffix="%" />
                <PriceChange value={0} suffix="%" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">規劃中的設定</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2 text-sm">
                {PLANNED.map((item) => (
                  <li key={item.name} className="flex items-center justify-between gap-2">
                    <span>{item.name}</span>
                    <Badge variant="secondary">{item.milestone}</Badge>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

const SHOWN = 200;

async function PriceGaps() {
  await requireUser();
  const db = getDb();
  const [gaps, total] = await Promise.all([listPendingGaps(db, SHOWN), countPendingGaps(db)]);
  return (
    <div className="space-y-3">
      {total > 0 ? (
        <p className="text-xs text-muted-foreground">
          共 {formatInteger(total)} 筆
          {total > SHOWN ? `，顯示前 ${SHOWN} 筆（有建議比例的排前面）` : ""}。
        </p>
      ) : null}
      <PriceGapList gaps={gaps} />
    </div>
  );
}
