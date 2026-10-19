import Link from "next/link";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { PortfolioSummary } from "@/components/portfolio/summary";
import { SessionRefresh } from "@/components/session-refresh";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { loadPortfolio } from "@/lib/portfolio-data";

const SECTIONS = [
  { title: "大盤與國際市場", milestone: "M1 / M5" },
  { title: "重大新聞與警示", milestone: "M6" },
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
        <div className="grid gap-3 md:grid-cols-3">
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
