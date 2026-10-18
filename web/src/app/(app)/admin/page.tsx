import type { Metadata } from "next";

import { PageHeader } from "@/components/coming-soon";
import { PriceChange } from "@/components/price-change";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

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
      <PageHeader title="設定" description="設定中心將隨里程碑建置。" />
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">規劃中的設定</CardTitle>
            <CardDescription>手動操作都會寫入稽核紀錄。</CardDescription>
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
        <Card>
          <CardHeader>
            <CardTitle className="text-base">漲跌配色</CardTitle>
            <CardDescription>
              目前為台股慣例（紅漲綠跌）。顏色來自語意 token <code>--color-up</code> /{" "}
              <code>--color-down</code>，日後可在此切換。
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-4 text-sm">
            <PriceChange value={1.25} suffix="%" />
            <PriceChange value={-0.8} suffix="%" />
            <PriceChange value={0} suffix="%" />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
