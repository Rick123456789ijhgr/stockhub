import type { Kysely } from "kysely";
import Link from "next/link";

import { TimeChart } from "@/components/charts/time-chart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatValue, periodLabel, type ValueFormat } from "@/lib/chart-format";
import type { DB } from "@/lib/db";
import { FINANCIAL_YEARS, financialWindowStart, inFinancialWindow } from "@/lib/financial-window";
import { getPeers, getValuationInputs, type PeerRow } from "@/lib/fundamentals";
import { taipeiToday } from "@/lib/market-hours";
import { cn } from "@/lib/utils";
import {
  type Metric,
  type MetricSummary,
  shiftYears,
  summarize,
  valuationSeries,
} from "@/lib/valuation";

import { RiverChart } from "./river-chart";

type StockInfo = { id: number; symbol: string; type: string; industry: string | null };

const PEERS_SHOWN = 15;

function level(percentile: number | null): string {
  if (percentile === null) return "";
  if (percentile >= 0.8) return "（偏高）";
  if (percentile <= 0.2) return "（偏低）";
  return "";
}

function SummaryTile({
  title,
  format,
  five,
  note,
}: {
  title: string;
  format: ValueFormat;
  five: MetricSummary;
  note?: string;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-xl tabular-nums">
          {five.current === null ? (note ?? "—") : formatValue(five.current, format)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-0.5 text-xs text-muted-foreground tabular-nums">
        <p>
          {FINANCIAL_YEARS} 年百分位{" "}
          <span className="text-foreground">
            {five.percentile === null ? "—" : `${Math.round(five.percentile * 100)}%`}
          </span>
          {level(five.percentile)}
        </p>
        {five.low !== null && five.high !== null ? (
          <p>
            區間 {formatValue(five.low, format)}～{formatValue(five.high, format)}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** 估值: P/E, P/B and yield percentiles, river chart, yield history, peer comparison. */
export async function ValuationSection({ db, stock }: { db: Kysely<DB>; stock: StockInfo }) {
  const today = taipeiToday();
  // Two extra years feed the trailing-four-quarter EPS and dividends at the window start.
  const start = financialWindowStart(today);
  const inputs = await getValuationInputs(db, stock.id, shiftYears(start, -2));
  if (inputs.prices.length === 0) return null;
  const points = inFinancialWindow(
    valuationSeries(inputs.prices, inputs.quarters, inputs.dividends),
    (p) => p.date,
    today,
  );
  if (points.length === 0) return null;
  const summary = (metric: Metric) => summarize(points, metric, FINANCIAL_YEARS);
  const isEtf = stock.type === "etf";
  const hasFundamentals = inputs.quarters.length > 0;
  const hasPe = points.some((p) => p.pe !== null);
  const peers =
    !isEtf && stock.industry ? await getPeers(db, stock.industry, today) : ([] as PeerRow[]);
  const yieldSeries = points.filter((_, i) => i % 5 === 0 || i === points.length - 1);

  return (
    <section aria-labelledby="valuation" className="space-y-4">
      <h2 id="valuation" className="sr-only">
        估值
      </h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {!isEtf && hasFundamentals ? (
          <>
            <SummaryTile
              title="本益比（近四季 EPS）"
              format="ratio"
              five={summary("pe")}
              note="虧損，不計算"
            />
            <SummaryTile
              title="股價淨值比"
              format="ratio"
              five={summary("pb")}
            />
          </>
        ) : null}
        <SummaryTile
          title="殖利率（近 12 個月現金股利）"
          format="percent"
          five={summary("dividendYield")}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        以收盤價（未還原）計算；百分位 = 期間內低於目前值的交易日比例，本益比排除虧損期。
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        {!isEtf && hasFundamentals ? (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">河流圖</CardTitle>
            </CardHeader>
            <CardContent>
              <RiverChart points={points} hasPe={hasPe} />
            </CardContent>
          </Card>
        ) : null}
        <Card size="sm">
          <CardHeader>
            <CardTitle className="text-sm">歷史殖利率</CardTitle>
            <CardDescription>
              近 12 個月現金股利 ÷ 當日收盤價；改為季配或半年配的那一年，12 個月內會含到較多次配息。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <TimeChart
              label="殖利率"
              format="percent"
              series={[
                {
                  name: "殖利率",
                  kind: "line",
                  color: "--series-1",
                  data: yieldSeries.map((p) => ({ time: p.date, value: p.dividendYield })),
                },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      {peers.length > 1 ? <PeerTable peers={peers} stockId={stock.id} industry={stock.industry} /> : null}
    </section>
  );
}

function PeerTable({
  peers,
  stockId,
  industry,
}: {
  peers: PeerRow[];
  stockId: number;
  industry: string | null;
}) {
  const shown = peers.slice(0, PEERS_SHOWN);
  const self = peers.find((p) => p.stockId === stockId);
  if (self && !shown.includes(self)) shown.push(self);
  const columns: { label: string; pick: (p: PeerRow) => number | null; format: ValueFormat }[] = [
    { label: "收盤", pick: (p) => p.close, format: "price" },
    { label: "市值", pick: (p) => p.marketCap, format: "hundredMillion" },
    { label: "本益比", pick: (p) => p.pe, format: "ratio" },
    { label: "股價淨值比", pick: (p) => p.pb, format: "ratio" },
    { label: "殖利率", pick: (p) => p.dividendYield, format: "percent" },
    { label: "ROE", pick: (p) => p.roeTtm, format: "percent" },
    { label: "毛利率", pick: (p) => p.grossMargin, format: "percent" },
    { label: "月營收年增", pick: (p) => p.revenueYoy, format: "percent" },
  ];
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">
          同業比較（{industry}，共 {peers.length} 家，依市值前 {PEERS_SHOWN} 家）
        </CardTitle>
        <CardDescription>ROE 與毛利率取已公布的最新一季（ROE 為近四季）。</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border bg-card">
          <Table className="min-w-[48rem] text-xs">
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-background">公司</TableHead>
                {columns.map((c) => (
                  <TableHead key={c.label} className="text-right">
                    {c.label}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((p) => (
                <TableRow key={p.stockId} className={cn(p.stockId === stockId && "bg-muted/60")}>
                  <TableCell className={cn("sticky left-0", p.stockId === stockId ? "bg-muted" : "bg-background")}>
                    <Link href={`/stocks/${p.symbol}`} className="hover:underline">
                      <span className="font-semibold tabular-nums">{p.symbol}</span> {p.name}
                    </Link>
                  </TableCell>
                  {columns.map((c) => (
                    <TableCell key={c.label} className="text-right tabular-nums">
                      {formatValue(c.pick(p), c.format)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {shown.some((p) => p.revenueMonth) ? (
          <p className="mt-2 text-xs text-muted-foreground">
            月營收為各公司最新公布月份（多為 {periodLabel(shown.find((p) => p.revenueMonth)?.revenueMonth ?? "", "month")}）。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
