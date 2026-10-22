"use client";

import Link from "next/link";

import { PriceChange } from "@/components/price-change";
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
import { formatLots, formatPrice } from "@/lib/format";
import { priceChange } from "@/lib/price";
import { MARKET_LABEL } from "@/lib/stock-market";
import type { StockListItem } from "@/lib/stocks";

/**
 * Search results as phone cards and a desktop table. A client component so a navigation
 * downloads the rows once as data, not twice as rendered elements (the page was ~850 KB,
 * docs/DECISIONS.md D-118).
 */
export function StockList({ stocks }: { stocks: StockListItem[] }) {
  return (
    <>
      <StockCards stocks={stocks} />
      <StockTable stocks={stocks} />
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
      {stock.delistedDate ? <Badge variant="outline" className="text-muted-foreground">已下市</Badge> : null}
    </span>
  );
}

/** Mobile: tappable cards. */
function StockCards({ stocks }: { stocks: StockListItem[] }) {
  return (
    <ul className="space-y-2 md:hidden">
      {stocks.map((s) => (
        <li key={`${s.symbol}-${s.delistedDate ?? ""}`}>
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
            <TableRow key={`${s.symbol}-${s.delistedDate ?? ""}`}>
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
