import { Search } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { PriceChange } from "@/components/price-change";
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
import { formatLots, formatPrice } from "@/lib/format";
import { priceChange } from "@/lib/price";
import { MARKET_LABEL, searchStocks, type StockListItem } from "@/lib/stocks";

export const metadata: Metadata = { title: "個股" };

export default function StocksPage({ searchParams }: PageProps<"/stocks">) {
  return (
    <>
      <PageHeader title="個股" description="輸入代號或名稱搜尋上市、上櫃股票與 ETF。" />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <StockSearch searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function StockSearch({ searchParams }: { searchParams: PageProps<"/stocks">["searchParams"] }) {
  await requireUser();
  const params = await searchParams;
  const q = (Array.isArray(params.q) ? params.q[0] : params.q)?.trim() ?? "";
  const stocks = await searchStocks(getDb(), q);

  return (
    <>
      <form action="/stocks" className="mb-4 flex gap-2" role="search">
        <label className="relative flex-1">
          <span className="sr-only">代號或名稱</span>
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            name="q"
            defaultValue={q}
            placeholder="例如 2330、台積電、0050"
            inputMode="search"
            autoComplete="off"
            className="h-10 w-full rounded-lg border bg-background pr-3 pl-9 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
          />
        </label>
        <button
          type="submit"
          className="h-10 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
        >
          搜尋
        </button>
      </form>

      {stocks.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {q ? `找不到「${q}」。` : "股票主檔是空的，請先執行 make etl-daily。"}
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="mb-2 text-xs text-muted-foreground">
            {q ? `「${q}」的搜尋結果` : "全部"}（最多顯示 100 筆）
          </p>
          <StockCards stocks={stocks} />
          <StockTable stocks={stocks} />
        </>
      )}
    </>
  );
}

function Change({ stock }: { stock: StockListItem }) {
  const change = priceChange(stock.close, stock.prevClose);
  return change ? (
    <PriceChange value={change.percent} suffix="%" />
  ) : (
    <span className="text-muted-foreground">—</span>
  );
}

function Labels({ stock }: { stock: StockListItem }) {
  return (
    <span className="flex items-center gap-1">
      <Badge variant="outline">{MARKET_LABEL[stock.market]}</Badge>
      {stock.type === "etf" ? <Badge variant="secondary">ETF</Badge> : null}
    </span>
  );
}

/** Mobile: tappable cards. */
function StockCards({ stocks }: { stocks: StockListItem[] }) {
  return (
    <ul className="space-y-2 md:hidden">
      {stocks.map((s) => (
        <li key={s.symbol}>
          <Link href={`/stocks/${s.symbol}`}>
            <Card size="sm">
              <CardContent className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm">{s.symbol}</span>
                    <span className="truncate font-medium">{s.name}</span>
                  </div>
                  <div className="mt-1">
                    <Labels stock={s} />
                  </div>
                </div>
                <div className="text-right tabular-nums">
                  <div className="font-medium">{formatPrice(s.close)}</div>
                  <div className="text-sm">
                    <Change stock={s} />
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Desktop: table. */
function StockTable({ stocks }: { stocks: StockListItem[] }) {
  return (
    <div className="hidden rounded-lg border md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>代號</TableHead>
            <TableHead>名稱</TableHead>
            <TableHead>類別</TableHead>
            <TableHead>產業</TableHead>
            <TableHead className="text-right">收盤</TableHead>
            <TableHead className="text-right">漲跌幅</TableHead>
            <TableHead className="text-right">成交量（張）</TableHead>
            <TableHead>資料日期</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stocks.map((s) => (
            <TableRow key={s.symbol}>
              <TableCell className="font-mono">
                <Link href={`/stocks/${s.symbol}`} className="underline-offset-4 hover:underline">
                  {s.symbol}
                </Link>
              </TableCell>
              <TableCell className="font-medium">
                <Link href={`/stocks/${s.symbol}`} className="underline-offset-4 hover:underline">
                  {s.name}
                </Link>
              </TableCell>
              <TableCell>
                <Labels stock={s} />
              </TableCell>
              <TableCell className="text-muted-foreground">{s.industry ?? "—"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(s.close)}</TableCell>
              <TableCell className="text-right">
                <Change stock={s} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatLots(s.volume)}</TableCell>
              <TableCell className="text-muted-foreground tabular-nums">{s.tradeDate ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
