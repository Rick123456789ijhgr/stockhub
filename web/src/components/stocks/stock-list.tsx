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
import { formatHundredMillion, formatLots, formatPrice } from "@/lib/format";
import { priceChange } from "@/lib/price";
import { MARKET_LABEL } from "@/lib/stock-market";
import type { Ranking, StockListItem } from "@/lib/stocks";
import { cn } from "@/lib/utils";

/** Which column a ranking sorts by (highlighted in the table, shown on phone cards). */
const RANK_COLUMN: Record<Ranking, Column> = {
  turnover: "turnover",
  volume: "volume",
  gainers: "change",
  losers: "change",
  marketCap: "marketCap",
};

type Column = "change" | "volume" | "turnover" | "marketCap";

/**
 * Search results or a ranking, as phone cards and a desktop table. A client component so a
 * navigation downloads the rows once as data, not twice as rendered elements (the page was
 * ~850 KB, docs/DECISIONS.md D-118).
 */
export function StockList({
  stocks,
  ranking,
  etf = false,
}: {
  stocks: StockListItem[];
  /** Set for a ranking: rows are numbered and its column is highlighted. */
  ranking?: Ranking;
  /** Only ETFs: no industry or market value columns (always empty for them). */
  etf?: boolean;
}) {
  const sorted = ranking ? RANK_COLUMN[ranking] : undefined;
  return (
    <>
      <StockCards stocks={stocks} sorted={sorted} numbered={ranking !== undefined} />
      <StockTable stocks={stocks} sorted={sorted} numbered={ranking !== undefined} etf={etf} />
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

/** The ranked figure under a card's labels (the change is already on the right). */
function CardMetric({ stock, column }: { stock: StockListItem; column: Column | undefined }) {
  if (column === "turnover") return <>成交 {formatHundredMillion(stock.turnover)} 億</>;
  if (column === "volume") return <>{formatLots(stock.volume)} 張</>;
  if (column === "marketCap") return <>市值 {formatHundredMillion(stock.marketCap, 0)} 億</>;
  return null;
}

/** Mobile: tappable cards. */
function StockCards({
  stocks,
  sorted,
  numbered,
}: {
  stocks: StockListItem[];
  sorted: Column | undefined;
  numbered: boolean;
}) {
  return (
    <ul className="space-y-2 md:hidden">
      {stocks.map((s, i) => (
        <li key={`${s.symbol}-${s.delistedDate ?? ""}`}>
          <Link href={`/stocks/${s.symbol}`}>
            <Card size="sm">
              <CardContent className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  {numbered ? (
                    <span className="w-5 shrink-0 text-right text-sm text-muted-foreground tabular-nums">
                      {i + 1}
                    </span>
                  ) : null}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold tabular-nums text-sm">{s.symbol}</span>
                      <span className="truncate font-medium">{s.name}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
                      <Labels stock={s} />
                      <CardMetric stock={s} column={sorted} />
                    </div>
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
function StockTable({
  stocks,
  sorted,
  numbered,
  etf,
}: {
  stocks: StockListItem[];
  sorted: Column | undefined;
  numbered: boolean;
  etf: boolean;
}) {
  // The ranked column stands out; a ranking is one trading day, so no date column.
  const head = (column: Column) =>
    cn("text-right", sorted === column && "font-semibold text-foreground");
  return (
    <div className="hidden overflow-hidden rounded-xl border bg-card shadow-card md:block">
      <Table>
        <TableHeader>
          <TableRow>
            {numbered ? <TableHead className="w-10 text-right">#</TableHead> : null}
            <TableHead>代號</TableHead>
            <TableHead>名稱</TableHead>
            <TableHead>類別</TableHead>
            {etf ? null : <TableHead>產業</TableHead>}
            <TableHead className="text-right">收盤</TableHead>
            <TableHead className={head("change")}>漲跌幅</TableHead>
            <TableHead className={head("volume")}>成交量（張）</TableHead>
            <TableHead className={head("turnover")}>成交金額（億）</TableHead>
            {etf ? null : <TableHead className={head("marketCap")}>市值（億）</TableHead>}
            {numbered ? null : <TableHead>資料日期</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {stocks.map((s, i) => (
            <TableRow key={`${s.symbol}-${s.delistedDate ?? ""}`}>
              {numbered ? (
                <TableCell className="text-right text-muted-foreground tabular-nums">{i + 1}</TableCell>
              ) : null}
              <TableCell className="font-semibold tabular-nums">
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
              {etf ? null : <TableCell className="text-muted-foreground">{s.industry ?? "—"}</TableCell>}
              <TableCell className="text-right tabular-nums">{formatPrice(s.close)}</TableCell>
              <TableCell className="text-right">
                <Change stock={s} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatLots(s.volume)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatHundredMillion(s.turnover)}</TableCell>
              {etf ? null : (
                <TableCell className="text-right tabular-nums">
                  {formatHundredMillion(s.marketCap, 0)}
                </TableCell>
              )}
              {numbered ? null : (
                <TableCell className="text-muted-foreground tabular-nums">{s.tradeDate ?? "—"}</TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
