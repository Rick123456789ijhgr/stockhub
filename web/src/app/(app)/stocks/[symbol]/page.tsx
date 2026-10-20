import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { FundamentalsSection } from "@/components/fundamentals/fundamentals-section";
import { ValuationSection } from "@/components/fundamentals/valuation-section";
import { PriceChange } from "@/components/price-change";
import { LiveQuote } from "@/components/stock-chart/live-quote";
import { StockChart } from "@/components/stock-chart/stock-chart";
import { StockDataRepair } from "@/components/stock-chart/stock-data-repair";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

export default function StockPage({ params }: PageProps<"/stocks/[symbol]">) {
  return (
    <>
      <Link
        href="/stocks"
        className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-4" aria-hidden />
        個股
      </Link>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <StockContent params={params} />
      </Suspense>
    </>
  );
}

async function StockContent({ params }: { params: PageProps<"/stocks/[symbol]">["params"] }) {
  await requireUser();
  const { symbol } = await params;
  const db = getDb();
  const stock = await findStock(db, decodeURIComponent(symbol));
  if (!stock) notFound();
  const bars = await getRecentBars(db, stock.id);
  const latest = bars[0];
  const change = latest ? priceChange(latest.close, latest.prevClose) : null;

  return (
    <>
      <header className="mb-4 md:mb-6">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{stock.name}</h1>
          <span className="font-mono text-muted-foreground">{stock.symbol}</span>
          <Badge variant="outline">{MARKET_LABEL[stock.market]}</Badge>
          {stock.type === "etf" ? <Badge variant="secondary">ETF</Badge> : null}
          {stock.delistedDate ? <Badge variant="outline" className="text-muted-foreground">已下市</Badge> : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {stock.industry ? `${stock.industry} · ` : ""}
          {stock.listedDateEstimated ? `最早資料 ${stock.listedDate}` : `上市（櫃）日 ${stock.listedDate}`}
          {stock.delistedDate ? ` · 終止上市（櫃）日 ${stock.delistedDate}` : ""}
        </p>
      </header>

      <LiveQuote
        symbol={stock.symbol}
        latestBarDate={latest?.tradeDate ?? null}
        canWatch={stock.delistedDate === null}
      />

      {latest ? (
        <Card className="mb-4">
          <CardHeader>
            <CardDescription>收盤（{latest.tradeDate}）</CardDescription>
            <CardTitle className="flex items-baseline gap-3 text-2xl tabular-nums">
              {formatPrice(latest.close)}
              {change ? (
                <span className="text-base">
                  <PriceChange value={change.change} />{" "}
                  <PriceChange value={change.percent} suffix="%" />
                </span>
              ) : null}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <Stat label="開盤" value={formatPrice(latest.open)} />
            <Stat label="最高" value={formatPrice(latest.high)} />
            <Stat label="最低" value={formatPrice(latest.low)} />
            <Stat label="成交量（張）" value={formatLots(latest.volume)} />
          </CardContent>
        </Card>
      ) : (
        <Card className="mb-4">
          <CardContent className="text-sm text-muted-foreground">
            尚無日線資料。執行 make etl-daily 或回填後再看。
          </CardContent>
        </Card>
      )}

      {bars.length > 0 ? <StockChart symbol={stock.symbol} /> : null}
      <StockDataRepair db={db} stockId={stock.id} symbol={stock.symbol} />
      <Suspense fallback={<Skeleton className="mt-6 h-64 w-full" />}>
        <FundamentalsSection db={db} stock={stock} />
      </Suspense>
      <Suspense fallback={<Skeleton className="mt-6 h-64 w-full" />}>
        <ValuationSection db={db} stock={stock} />
      </Suspense>
      {bars.length > 0 ? <div className="mt-6"><BarsTable bars={bars} /></div> : null}
      <p className="mt-3 text-xs text-muted-foreground">
        表格為交易所公布的原始價；漲跌以前一交易日收盤計算，除權息日改以參考價（前收乘上還原因子）為基準，與交易所的漲跌一致。
      </p>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular-nums">{value}</div>
    </div>
  );
}

function BarsTable({ bars }: { bars: DailyBarRow[] }) {
  return (
    <section aria-labelledby="bars">
      <h2 id="bars" className="mb-2 text-base font-semibold">
        近 {bars.length} 個交易日
      </h2>
      {/* Wide table scrolls inside its own box on phones; the page itself never scrolls sideways. */}
      <div className="overflow-x-auto rounded-lg border">
        <Table className="min-w-[40rem]">
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
            {bars.map((bar) => {
              const change = priceChange(bar.close, bar.prevClose);
              return (
                <TableRow key={bar.tradeDate}>
                  <TableCell className="sticky left-0 bg-background tabular-nums">
                    {bar.tradeDate}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatPrice(bar.open)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPrice(bar.high)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPrice(bar.low)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPrice(bar.close)}</TableCell>
                  <TableCell className="text-right">
                    {change ? <PriceChange value={change.change} /> : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatLots(bar.volume)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatHundredMillion(bar.turnover)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
