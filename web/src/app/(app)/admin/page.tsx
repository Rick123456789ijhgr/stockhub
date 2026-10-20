import type { Metadata } from "next";
import { Suspense } from "react";

import { AuditLogList } from "@/components/admin/audit-log";
import { FeeSettingsForm } from "@/components/admin/fee-settings-form";
import { FinancialsQuarantineList } from "@/components/admin/financials-quarantine-review";
import { PriceGapList } from "@/components/admin/price-gap-review";
import { AppearanceSettings } from "@/components/appearance-controls";
import { PageHeader } from "@/components/coming-soon";
import { Disclosure, InfoNote } from "@/components/disclosure";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { PriceChange } from "@/components/price-change";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listAuditLog } from "@/lib/audit";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { formatInteger } from "@/lib/format";
import { countQuarantinedStatements, listQuarantinedStatements } from "@/lib/fundamentals-status";
import { countPendingGaps, listPendingGaps } from "@/lib/price-gaps";
import { getFeeSettings } from "@/lib/settings";

export const metadata: Metadata = { title: "設定" };

const PLANNED = [
  { name: "題材編輯", milestone: "M5" },
  { name: "警示規則", milestone: "M6" },
  { name: "排程管理", milestone: "之後" },
];

type Tab = "general" | "review" | "audit";

export default function AdminPage({ searchParams }: PageProps<"/admin">) {
  return (
    <>
      <PageHeader title="設定" description="資料確認與顯示設定；手動操作都會寫入稽核紀錄。" />
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <AdminContent searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function AdminContent({ searchParams }: { searchParams: PageProps<"/admin">["searchParams"] }) {
  await requireUser();
  const db = getDb();
  const [query, gapCount, quarantineCount] = await Promise.all([
    searchParams,
    countPendingGaps(db),
    countQuarantinedStatements(db),
  ]);
  const tabs: PageTab<Tab>[] = [
    { key: "general", label: "一般" },
    { key: "review", label: "待確認", badge: gapCount + quarantineCount },
    { key: "audit", label: "稽核紀錄" },
  ];
  const tab = activeTab(tabs, query.tab);

  return (
    <div className="space-y-3">
      <PageTabs tabs={tabs} active={tab} basePath="/admin" />
      {tab === "general" ? <General /> : null}
      {tab === "review" ? (
        <Card size="sm">
          <CardContent className="divide-y">
            <Disclosure
              className="pb-2"
              defaultOpen={gapCount > 0}
              summary="價格跳空"
              meta={`${formatInteger(gapCount)} 筆`}
            >
              <div className="space-y-1 pl-5">
                <InfoNote>
                  還原價相鄰兩日變動超出 −40%～+50%，而且沒有任何已知事件可以解釋（多半是櫃買的面額變更、ETF
                  分割或早年減資）。確認後記為手動事件；之後若匯入官方事件，會自動取代手動紀錄。還原價在下次執行{" "}
                  <code>compute_adj_factors</code>（<code>make etl-daily</code> 或{" "}
                  <code>make etl-adjust</code>）時更新。
                </InfoNote>
                <Suspense fallback={<Skeleton className="h-40 w-full" />}>
                  <PriceGaps total={gapCount} />
                </Suspense>
              </div>
            </Disclosure>
            <Disclosure
              className="pt-2"
              defaultOpen={gapCount === 0 && quarantineCount > 0}
              summary="財報"
              meta={`${formatInteger(quarantineCount)} 筆`}
            >
              <div className="space-y-1 pl-5">
                <InfoNote>
                  品質檢查沒過的整份報表（例如資料源把年初至今的累計數當成單季），沒有寫入正式資料。通常選「捨棄」：資料源修正後，下次抓取通過檢查就會自動取代；確定沒問題才選「仍然採用」。
                </InfoNote>
                <Suspense fallback={<Skeleton className="h-32 w-full" />}>
                  <FinancialsQuarantine total={quarantineCount} />
                </Suspense>
              </div>
            </Disclosure>
          </CardContent>
        </Card>
      ) : null}
      {tab === "audit" ? (
        <Card size="sm">
          <CardHeader>
            <CardDescription>最近 {AUDIT_SHOWN} 筆手動操作（交易、自選、設定、事件確認）。</CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-40 w-full" />}>
              <AuditLog />
            </Suspense>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function General() {
  return (
    <div className="grid items-start gap-3 lg:grid-cols-[3fr_2fr]">
      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">手續費</CardTitle>
          <CardDescription>
            新增交易時自動帶入手續費與證交稅，也用來估算持股的賣出成本。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <Fees />
          </Suspense>
        </CardContent>
      </Card>
      <div className="grid gap-3">
        <Card size="sm">
          <CardHeader>
            <CardTitle className="text-sm">顯示</CardTitle>
            <CardDescription>深色模式與漲跌配色；圖表會跟著切換。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <AppearanceSettings />
            <div className="flex gap-4 text-sm">
              <PriceChange value={1.25} suffix="%" />
              <PriceChange value={-0.8} suffix="%" />
              <PriceChange value={0} suffix="%" />
            </div>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle className="text-sm">規劃中的設定</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm">
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
  );
}

const AUDIT_SHOWN = 100;

async function Fees() {
  await requireUser();
  return <FeeSettingsForm initial={await getFeeSettings(getDb())} />;
}

async function AuditLog() {
  await requireUser();
  return <AuditLogList entries={await listAuditLog(getDb(), { limit: AUDIT_SHOWN })} />;
}

const SHOWN = 200;

async function PriceGaps({ total }: { total: number }) {
  await requireUser();
  const gaps = await listPendingGaps(getDb(), SHOWN);
  return (
    <div className="space-y-1">
      {total > SHOWN ? (
        <p className="text-xs text-muted-foreground">
          共 {formatInteger(total)} 筆，載入前 {SHOWN} 筆（有建議比例的排前面）；處理後重新整理可載入其餘。
        </p>
      ) : null}
      <PriceGapList gaps={gaps} />
    </div>
  );
}

async function FinancialsQuarantine({ total }: { total: number }) {
  await requireUser();
  const rows = await listQuarantinedStatements(getDb(), SHOWN);
  return (
    <div className="space-y-1">
      {total > SHOWN ? (
        <p className="text-xs text-muted-foreground">
          共 {formatInteger(total)} 筆，載入最新的 {SHOWN} 筆；處理後重新整理可載入其餘。
        </p>
      ) : null}
      <FinancialsQuarantineList rows={rows} />
    </div>
  );
}
