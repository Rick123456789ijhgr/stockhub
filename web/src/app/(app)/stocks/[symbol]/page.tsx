import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ChipsSection } from "@/components/chips/chips-section";
import { FundamentalsSection } from "@/components/fundamentals/fundamentals-section";
import { ValuationSection } from "@/components/fundamentals/valuation-section";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { RememberedLink } from "@/components/nav/remembered-link";
import { PriceChange } from "@/components/price-change";
import { ShowMoreRows } from "@/components/show-more";
import { QuotePanel, QuoteStatus, WatchButton } from "@/components/stock-chart/live-quote";
import { StockChart } from "@/components/stock-chart/stock-chart";
import { StockDataRepair } from "@/components/stock-chart/stock-data-repair";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
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
import { getQuoteFundamentals } from "@/lib/fundamentals";
import { stockThemes } from "@/lib/heatmap";
import { taipeiToday } from "@/lib/market-hours";
import { priceChange } from "@/lib/price";
import {
  CHART_RECENT_MONTHS,
  type DailyBarRow,
  findStock,
  getChartBars,
  getRecentBars,
  MARKET_LABEL,
} from "@/lib/stocks";

type Tab = "chart" | "fundamentals" | "valuation" | "chips" | "daily";
const STOCK_TABS: PageTab<Tab>[] = [
  { key: "chart", label: "走勢" },
  { key: "fundamentals", label: "基本面" },
  { key: "valuation", label: "估值" },
  { key: "chips", label: "籌碼" },
  { key: "daily", label: "歷史日線" },
];
/** ETFs have no statements. */
const ETF_TABS = STOCK_TABS.filter((t) => t.key !== "fundamentals");
const BARS_SHOWN = 20;

export default function StockPage({ params, searchParams }: PageProps<"/stocks/[symbol]">) {
  return (
    <>
      <RememberedLink
        href="/stocks"
        className="mb-3 inline-flex items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-4" aria-hidden />
        個股
      </RememberedLink>
      <StockContent params={params} searchParams={searchParams} />
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
  const tabs = stock.type === "etf" ? ETF_TABS : STOCK_TABS;
  const tab = activeTab(tabs, query.tab);
  // Not awaited: the chart's bars stream in with the page instead of being fetched after it.
  const chartBars =
    tab === "chart" ? getChartBars(db, stock.id, CHART_RECENT_MONTHS).catch(() => null) : null;
  const [bars, fundamentals, themes] = await Promise.all([
    getRecentBars(db, stock.id),
    getQuoteFundamentals(db, stock.id, taipeiToday()),
    stockThemes(db, stock.id, taipeiToday()),
  ]);

  // Futu's order: section tabs on top, then the quote header, then the section.
  return (
    <div className="space-y-4">
      <PageTabs tabs={tabs} active={tab} basePath={`/stocks/${stock.symbol}`} />
      <Card>
        <CardContent className="space-y-4">
          <header className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span className="font-mono text-lg font-semibold">{stock.symbol}</span>
                <h1 className="text-lg font-semibold tracking-tight md:text-xl">{stock.name}</h1>
                <Badge variant="outline">{MARKET_LABEL[stock.market]}</Badge>
                {stock.type === "etf" ? <Badge variant="secondary">ETF</Badge> : null}
                {stock.delistedDate ? (
                  <Badge variant="outline" className="text-muted-foreground">
                    已下市
                  </Badge>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                <QuoteStatus symbol={stock.symbol} latest={bars[0]} />
                {stock.industry ? (
                  <>
                    {" · "}
                    <Link href="/market?tab=heatmap" className="hover:text-foreground hover:underline">
                      {stock.industry}
                    </Link>
                  </>
                ) : null}
                {themes.map((t) => (
                  <span key={t.id}>
                    {" · "}
                    <Link href="/market?tab=heatmap&by=theme" className="hover:text-foreground hover:underline">
                      #{t.name}
                    </Link>
                  </span>
                ))}
                <span className="hidden sm:inline">
                  {stock.listedDateEstimated
                    ? ` · 最早資料 ${stock.listedDate}`
                    : ` · 上市（櫃）日 ${stock.listedDate}`}
                </span>
                {stock.delistedDate ? ` · 終止上市（櫃）日 ${stock.delistedDate}` : ""}
              </p>
            </div>
            {stock.delistedDate === null ? <WatchButton symbol={stock.symbol} /> : null}
          </header>
          <QuotePanel
            symbol={stock.symbol}
            latest={bars[0]}
            fundamentals={fundamentals}
            isEtf={stock.type === "etf"}
          />
        </CardContent>
      </Card>

      <div className="pt-2">
        {tab === "chart" ? (
          <div className="space-y-4">
            {bars.length > 0 && chartBars ? (
              <StockChart symbol={stock.symbol} initial={chartBars} />
            ) : null}
            <StockDataRepair db={db} stockId={stock.id} symbol={stock.symbol} />
          </div>
        ) : null}
        {tab === "fundamentals" ? <FundamentalsSection db={db} stock={stock} /> : null}
        {tab === "valuation" ? <ValuationSection db={db} stock={stock} /> : null}
        {tab === "chips" ? <ChipsSection db={db} stock={stock} /> : null}
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
