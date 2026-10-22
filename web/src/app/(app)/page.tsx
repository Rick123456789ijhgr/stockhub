import Link from "next/link";

import { FlowRanking } from "@/components/chips/flow-ranking";
import { MarketStrip } from "@/components/market/market-strip";
import { PageHeader } from "@/components/coming-soon";
import { PortfolioSummary } from "@/components/portfolio/summary";
import { PriceChange } from "@/components/price-change";
import { SessionRefresh } from "@/components/session-refresh";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { listRecentAlerts } from "@/lib/alerts";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";
import { loadPortfolio } from "@/lib/portfolio-data";

export default function HomePage() {
  return (
    <>
      <PageHeader title="首頁" description="持股、市場、警示與法人動向。" />
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
            <Holdings />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              大盤與國際市場
              <Link href="/market" className="text-sm font-normal text-muted-foreground hover:text-foreground">
                市場 →
              </Link>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Markets />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              警示
              <Badge variant="secondary">新聞 M6</Badge>
            </CardTitle>
            <CardDescription>
              持股單日漲跌超過近 20 日報酬標準差 × 2.5（最低 3%）時，盤中輪詢與收盤後各檢查一次；外資、投信或自營商單日買賣超達持股成交量
              10%（成交金額 5,000 萬以上）時，抓完籌碼後檢查；景氣燈號變色或 Fed 調整利率時也會提醒。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Alerts />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">三大法人買賣超排行</CardTitle>
          </CardHeader>
          <CardContent>
            <Flows />
          </CardContent>
        </Card>
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

async function Markets() {
  await requireUser();
  return <MarketStrip db={getDb()} today={taipeiToday()} />;
}

async function Flows() {
  await requireUser();
  return <FlowRanking db={getDb()} />;
}

async function Alerts() {
  await requireUser();
  const alerts = await listRecentAlerts(getDb());
  if (alerts.length === 0) return <p className="text-sm text-muted-foreground">最近沒有警示。</p>;
  return (
    <ul className="divide-y text-sm">
      {alerts.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
          <Link href={a.symbol ? `/stocks/${a.symbol}` : "/market?tab=macro"} className="font-medium hover:underline">
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
            {a.kind === "holding_move" && a.threshold !== null ? `（門檻 ±${(a.threshold * 100).toFixed(1)}%）` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
