import Link from "next/link";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { PortfolioSummary } from "@/components/portfolio/summary";
import { PriceChange } from "@/components/price-change";
import { SessionRefresh } from "@/components/session-refresh";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listRecentAlerts } from "@/lib/alerts";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { loadPortfolio } from "@/lib/portfolio-data";

const SECTIONS = [
  { title: "大盤與國際市場", milestone: "M1 / M5" },
  { title: "三大法人買賣超排行", milestone: "M4" },
];

export default function HomePage() {
  return (
    <>
      <PageHeader title="首頁" description="各區塊會隨里程碑逐步上線。" />
      <div className="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              持股損益與今日漲跌
              <Link href="/portfolio" className="text-sm font-normal text-muted-foreground hover:text-foreground">
                持股明細 →
              </Link>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-24 w-full" />}>
              <Holdings />
            </Suspense>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              警示
              <Badge variant="secondary">新聞與總經 M6</Badge>
            </CardTitle>
            <CardDescription>
              持股單日漲跌超過近 20 日報酬標準差 × 2.5（最低 3%）時，盤中輪詢與收盤後各檢查一次。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Suspense fallback={<Skeleton className="h-16 w-full" />}>
              <Alerts />
            </Suspense>
          </CardContent>
        </Card>
        <div className="grid gap-3 md:grid-cols-2">
          {SECTIONS.map((section) => (
            <Card key={section.title}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2 text-base">
                  {section.title}
                  <Badge variant="secondary">{section.milestone}</Badge>
                </CardTitle>
                <CardDescription>即將推出</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      </div>
    </>
  );
}

async function Holdings() {
  await requireUser();
  const view = await loadPortfolio(getDb());
  if (view.transactions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        還沒有交易紀錄。<Link href="/portfolio#add" className="underline underline-offset-2">新增第一筆交易</Link>
      </p>
    );
  }
  const live = view.ledger.positions.some((p) => p.shares > 0 && view.marks[p.stock]?.source === "quote");
  return (
    <>
      {live ? <SessionRefresh /> : null}
      <PortfolioSummary totals={view.totals} />
    </>
  );
}

async function Alerts() {
  await requireUser();
  const alerts = await listRecentAlerts(getDb());
  if (alerts.length === 0) return <p className="text-sm text-muted-foreground">最近沒有警示。</p>;
  return (
    <ul className="divide-y text-sm">
      {alerts.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
          <Link href={`/stocks/${a.symbol}`} className="font-medium hover:underline">
            {a.title}
          </Link>
          <span className="text-xs text-muted-foreground tabular-nums">
            {a.tradeDate}
            {a.change !== null ? (
              <>
                {" "}
                <PriceChange value={a.change * 100} suffix="%" />
              </>
            ) : null}
            {a.threshold !== null ? `（門檻 ±${(a.threshold * 100).toFixed(1)}%）` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
