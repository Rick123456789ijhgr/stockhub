import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { DividendList } from "@/components/portfolio/dividend-list";
import { HoldingsTable, Pnl, RealizedList, UpcomingList } from "@/components/portfolio/holdings";
import { PortfolioSummary } from "@/components/portfolio/summary";
import { ShowAll, TransactionsPanel } from "@/components/portfolio/transactions-panel";
import { SessionRefresh } from "@/components/session-refresh";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { describeFeeSettings } from "@/lib/fee-settings";
import { formatInteger } from "@/lib/format";
import { loadPortfolio } from "@/lib/portfolio-data";

export const metadata: Metadata = { title: "持股" };

/** Newest entries sent to the browser by default; `?all=1` shows everything. */
const RECENT = { transactions: 50, dividends: 30, realized: 30 };

const byDateDesc = <T,>(date: (x: T) => string) => (a: T, b: T) =>
  date(a) < date(b) ? 1 : date(a) > date(b) ? -1 : 0;

export default function PortfolioPage({ searchParams }: PageProps<"/portfolio">) {
  return (
    <>
      <PageHeader
        title="持股"
        description="平均成本法；除權息不調整成本，股利另列收入。盤中有報價時用報價（每 30 秒更新）。"
      />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <PortfolioContent searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function PortfolioContent({
  searchParams,
}: {
  searchParams: PageProps<"/portfolio">["searchParams"];
}) {
  await requireUser();
  const all = (await searchParams).all === "1";
  const view = await loadPortfolio(getDb());
  const cut = <T,>(items: T[], n: number) => (all ? items : items.slice(0, n));
  const dividends = [...view.ledger.dividends].sort(byDateDesc((d) => d.exDate));
  const realized = [...view.ledger.realized].sort(byDateDesc((r) => r.date));
  const { ledger, stocks, marks } = view;
  const open = ledger.positions.filter((p) => p.shares > 0);
  const closed = ledger.positions.filter((p) => p.shares === 0);
  const live = open.some((p) => marks[p.stock]?.source === "quote");
  const missing = open.filter((p) => !marks[p.stock]);

  return (
    <div className="space-y-3">
      {live ? <SessionRefresh /> : null}
      <PortfolioSummary totals={view.totals} />

      {ledger.issues.length > 0 ? (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-base text-destructive">有賣出超過當時的持股</CardTitle>
            <CardDescription>
              這些交易沒有計入損益。通常是減資、分割的比例和實際不同，或漏記了買進；請修改交易。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="text-sm tabular-nums">
              {ledger.issues.map((i) => (
                <li key={i.id}>
                  {i.date} {stocks[i.stock]?.symbol} 賣出 {formatInteger(i.quantity)} 股，當時持有{" "}
                  {formatInteger(i.held)} 股
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">持股</CardTitle>
          <CardDescription>
            未實現損益已扣除預估的賣出手續費與證交稅。今日損益含今天的買賣（以成交價計）。
            {missing.length > 0
              ? ` ${missing.map((p) => stocks[p.stock]?.symbol).join("、")} 沒有價格，只計成本。`
              : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <HoldingsTable positions={open} stocks={stocks} marks={marks} />
        </CardContent>
      </Card>

      <Card id="transactions" className="scroll-mt-4">
        <CardHeader>
          <CardTitle className="text-base">交易紀錄</CardTitle>
          <CardDescription>
            數量以股計。手續費依 <Link href="/admin" className="underline underline-offset-2">設定</Link>
            自動帶入（{describeFeeSettings(view.fees)}）；證交稅股票 0.3%、ETF 0.1%、債券 ETF
            免徵、當沖減半，都可以手動修改。新增、修改、刪除都會寫入稽核紀錄。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TransactionsPanel
            transactions={cut(view.transactions, RECENT.transactions)}
            total={view.transactions.length}
            fees={view.fees}
            today={view.asOf}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">即將除權息（預估）</CardTitle>
          <CardDescription>
            交易所的除權除息預告表（每天開盤前與收盤後更新），以目前持股推算；ETF
            常在除息前幾天才公告金額。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <UpcomingList upcoming={view.upcoming} stocks={stocks} />
        </CardContent>
      </Card>

      <Card id="dividends" className="scroll-mt-4">
        <CardHeader>
          <CardTitle className="text-base">配息與股數變動</CardTitle>
          <CardDescription>
            依除權息日前一交易日的持股，乘上交易所公布的每股現金股利、配股率或減資、分割比例推算（標示「估算」）。
            實際入帳會扣匯費與二代健保補充保費；收到入帳通知後可以輸入實收，損益改用實收數字。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DividendList
            dividends={cut(dividends, RECENT.dividends)}
            stocks={stocks}
            receipts={view.receipts}
          />
          <ShowAll shown={cut(dividends, RECENT.dividends).length} total={dividends.length} anchor="dividends" />
        </CardContent>
      </Card>

      <Card id="realized" className="scroll-mt-4">
        <CardHeader>
          <CardTitle className="text-base">已實現損益</CardTitle>
          <CardDescription>賣出收入扣除手續費、證交稅與平均成本。</CardDescription>
        </CardHeader>
        <CardContent>
          <RealizedList realized={cut(realized, RECENT.realized)} stocks={stocks} />
          <ShowAll shown={cut(realized, RECENT.realized).length} total={realized.length} anchor="realized" />
        </CardContent>
      </Card>

      {closed.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">已出清</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {closed.map((p) => (
                <li key={p.stock} className="flex items-baseline justify-between gap-3 py-2">
                  <Link href={`/stocks/${stocks[p.stock]?.symbol}`} className="hover:underline">
                    <span className="font-mono">{stocks[p.stock]?.symbol}</span> {stocks[p.stock]?.name}
                  </Link>
                  <span className="text-xs text-muted-foreground">
                    已實現 <Pnl value={p.realized} />
                    {p.dividends > 0 ? ` · 股利 ${formatInteger(p.dividends)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
