import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { FundamentalsSection } from "@/components/fundamentals/fundamentals-section";
import { ValuationSection } from "@/components/fundamentals/valuation-section";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { PriceChange } from "@/components/price-change";
import { ShowMoreRows } from "@/components/show-more";
import { QuotePanel, WatchButton } from "@/components/stock-chart/live-quote";
import { StockChart } from "@/components/stock-chart/stock-chart";
import { StockDataRepair } from "@/components/stock-chart/stock-data-repair";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { formatHundredMillion, formatLots, formatPrice } from "@/lib/format";
import { priceChange } from "@/lib/price";
import { type DailyBarRow, findStock, getRecentBars, MARKET_LABEL } from "@/lib/stocks";

type Tab = "fundamentals" | "valuation" | "daily";
const STOCK_TABS: PageTab<Tab>[] = [
  { key: "fundamentals", label: "基本面" },
  { key: "valuation", label: "估值" },
  { key: "daily", label: "歷史日線" },
];
/** ETFs have no statements; their first tab is valuation (yield). */
const ETF_TABS = STOCK_TABS.filter((t) => t.key !== "fundamentals");
const BARS_SHOWN = 20;

export default function StockPage({ params, searchParams }: PageProps<"/stocks/[symbol]">) {
  return (
    <>
      <Link
        href="/stocks"
        className="mb-3 inline-flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-4" aria-hidden />
        個股
      </Link>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <StockContent params={params} searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function StockContent({
  params,
  searchParams,
}: {
  params: PageProps<"/stocks/[symbol]">["params"];
  searchParams: PageProps<"/stocks/[symbol]">["searchParams"];
}) {
  await requireUser();
  const [{ symbol }, query] = await Promise.all([params, searchParams]);
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) notFound();
  const bars = await getRecentBars(db, stock.id);
  const tabs = stock.type === "etf" ? ETF_TABS : STOCK_TABS;
  const tab = activeTab(tabs, query.tab);

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-4">
          <header className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{stock.name}</h1>
                <span className="font-mono text-sm text-muted-foreground">{stock.symbol}</span>
                <Badge variant="outline">{MARKET_LABEL[stock.market]}</Badge>
                {stock.type === "etf" ? <Badge variant="secondary">ETF</Badge> : null}
                {stock.delistedDate ? (
                  <Badge variant="outline" className="text-muted-foreground">
                    已下市
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {stock.industry ? `${stock.industry} · ` : ""}
                {stock.listedDateEstimated
                  ? `最早資料 ${stock.listedDate}`
                  : `上市（櫃）日 ${stock.listedDate}`}
                {stock.delistedDate ? ` · 終止上市（櫃）日 ${stock.delistedDate}` : ""}
              </p>
            </div>
            {stock.delistedDate === null ? <WatchButton symbol={stock.symbol} /> : null}
          </header>
          <QuotePanel symbol={stock.symbol} latest={bars[0]} />
        </CardContent>
      </Card>

      {bars.length > 0 ? <StockChart symbol={stock.symbol} /> : null}
      <StockDataRepair db={db} stockId={stock.id} symbol={stock.symbol} />

      <div className="space-y-4">
        <PageTabs tabs={tabs} active={tab} basePath={`/stocks/${stock.symbol}`} />
        <Suspense key={tab} fallback={<Skeleton className="h-64 w-full" />}>
          {tab === "fundamentals" ? <FundamentalsSection db={db} stock={stock} /> : null}
          {tab === "valuation" ? <ValuationSection db={db} stock={stock} /> : null}
        </Suspense>
        {tab === "daily" ? (
          bars.length > 0 ? (
            <BarsTable bars={bars} />
          ) : (
            <p className="text-sm text-muted-foreground">尚無日線資料。</p>
          )
        ) : null}
      </div>
    </div>
  );
}

function BarsTable({ bars }: { bars: DailyBarRow[] }) {
  const rows = bars.map((bar) => {
    const change = priceChange(bar.close, bar.prevClose);
    return (
      <TableRow key={bar.tradeDate}>
        <TableCell className="sticky left-0 bg-background tabular-nums">{bar.tradeDate}</TableCell>
        <TableCell className="text-right tabular-nums">{formatPrice(bar.open)}</TableCell>
        <TableCell className="text-right tabular-nums">{formatPrice(bar.high)}</TableCell>
        <TableCell className="text-right tabular-nums">{formatPrice(bar.low)}</TableCell>
        <TableCell className="text-right tabular-nums">{formatPrice(bar.close)}</TableCell>
        <TableCell className="text-right">
          {change ? <PriceChange value={change.change} /> : "—"}
        </TableCell>
        <TableCell className="text-right tabular-nums">{formatLots(bar.volume)}</TableCell>
        <TableCell className="text-right tabular-nums">{formatHundredMillion(bar.turnover)}</TableCell>
      </TableRow>
    );
  });
  return (
    <section aria-labelledby="bars" className="space-y-3">
      <h2 id="bars" className="sr-only">
        近 {bars.length} 個交易日
      </h2>
      {/* Wide table scrolls inside its own box on phones; the page itself never scrolls sideways. */}
      <div className="overflow-x-auto rounded-lg border">
        <Table className="min-w-[40rem] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 bg-background">日期</TableHead>
              <TableHead className="text-right">開盤</TableHead>
              <TableHead className="text-right">最高</TableHead>
              <TableHead className="text-right">最低</TableHead>
              <TableHead className="text-right">收盤</TableHead>
              <TableHead className="text-right">漲跌</TableHead>
              <TableHead className="text-right">成交量（張）</TableHead>
              <TableHead className="text-right">成交金額（億）</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <ShowMoreRows rows={rows} initial={BARS_SHOWN} colSpan={8} />
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        近 {bars.length} 個交易日，交易所公布的原始價；漲跌以前一交易日收盤計算，除權息日改以參考價（前收乘上還原因子）為基準，與交易所的漲跌一致。
      </p>
    </section>
  );
}
