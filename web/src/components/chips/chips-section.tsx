import type { Kysely } from "kysely";

import { type ChartSeries, TimeChart } from "@/components/charts/time-chart";
import { InfoNote } from "@/components/disclosure";
import { directionClass } from "@/components/price-change";
import { ShowMoreRows } from "@/components/show-more";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatValue, periodLabel } from "@/lib/chart-format";
import {
  type ChipDay,
  type ChipSummary,
  getChipDays,
  getChipSummary,
  getHolderWeeks,
  type HolderWeek,
} from "@/lib/chips";
import type { DB } from "@/lib/db";
import { cn } from "@/lib/utils";

type StockInfo = { id: number; symbol: string; market: string };

const CHART_DAYS = 120;
const TABLE_ROWS = 10;
const TABLE_DAYS = 60;

/** Net shares in lots, signed and colored by direction (buying = up color). */
function Lots({ shares, className }: { shares: number | null; className?: string }) {
  if (shares === null) return <span className="text-muted-foreground">—</span>;
  const lots = Math.round(shares / 1000);
  return (
    <span className={cn("tabular-nums", directionClass(lots), className)}>
      {lots > 0 ? "+" : ""}
      {lots.toLocaleString("zh-TW")}
    </span>
  );
}

function streakLabel(days: number): string {
  if (days > 0) return `連買 ${days} 日`;
  if (days < 0) return `連賣 ${-days} 日`;
  return "持平";
}

function points(rows: ChipDay[], pick: (d: ChipDay) => number | null) {
  return rows.map((d) => ({ time: d.date, value: pick(d) }));
}

function signedBars(name: string, rows: ChipDay[], pick: (d: ChipDay) => number | null): ChartSeries {
  return { name, kind: "histogram", color: "--series-1", signed: true, data: points(rows, pick) };
}

/** 籌碼: institutional flows, margin, foreign holdings and TDCC big holders of one stock. */
export async function ChipsSection({ db, stock }: { db: Kysely<DB>; stock: StockInfo }) {
  const [summary, { rows, institutionalSince }, weeks] = await Promise.all([
    getChipSummary(db, stock.id),
    getChipDays(db, stock.id, stock.market, Math.max(CHART_DAYS, TABLE_DAYS)),
    getHolderWeeks(db, stock.id),
  ]);
  if (rows.length === 0 && weeks.length === 0) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">
          還沒有這一檔的籌碼資料（每日 18:00 與 21:30 更新，歷史回填進行中）。
        </CardContent>
      </Card>
    );
  }
  const recent = rows.slice(-CHART_DAYS);
  const hasMargin = recent.some((d) => d.marginBalance !== null);
  const hasHoldings = recent.some((d) => d.foreignRatio !== null);

  return (
    <section aria-labelledby="chips" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="chips" className="sr-only">
          籌碼
        </h2>
        <InfoNote>
          三大法人、融資融券、外資持股來自證交所與櫃買中心的每日公告，集保股權分散表每週一次。張數 = 股數 ÷
          1,000；外資不含外資自營商（交易所把外資自營商算在自營商內）。上櫃的三大法人資料從 2014-12-01
          起才有{institutionalSince ? `（本檔所屬市場最早 ${institutionalSince}）` : ""}
          。集保官方只公開最新一週，所以大戶資料從 2026-10 開始逐週累積。
        </InfoNote>
        {summary ? (
          <span className="text-xs text-muted-foreground tabular-nums">資料日 {summary.tradeDate}</span>
        ) : null}
      </div>

      {summary ? <SummaryTiles summary={summary} /> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {recent.some((d) => d.totalNet !== null) ? (
          <Card size="sm" className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">三大法人買賣超（張）</CardTitle>
              <CardDescription>近 {recent.length} 個交易日，買超為正</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <TimeChart
                label="三大法人合計"
                format="lots"
                series={[signedBars("合計", recent, (d) => d.totalNet)]}
              />
              <div className="grid gap-4 md:grid-cols-3">
                <TimeChart label="外資" format="lots" height={150} series={[signedBars("外資", recent, (d) => d.foreignNet)]} />
                <TimeChart label="投信" format="lots" height={150} series={[signedBars("投信", recent, (d) => d.trustNet)]} />
                <TimeChart
                  label="自營商"
                  format="lots"
                  height={150}
                  series={[signedBars("自營商", recent, (d) => d.dealerNet)]}
                />
              </div>
            </CardContent>
          </Card>
        ) : null}
        {hasMargin ? (
          <Card size="sm" className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">融資融券餘額（張）</CardTitle>
              {summary ? (
                <CardDescription className="tabular-nums">
                  融資使用率 {formatValue(summary.marginUtilization, "percent")}，券資比{" "}
                  {formatValue(summary.shortMarginRatio, "percent")}
                </CardDescription>
              ) : null}
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <TimeChart
                label="融資餘額"
                format="lots"
                series={[{ name: "融資", kind: "line", color: "--series-1", data: points(recent, (d) => d.marginBalance) }]}
              />
              <TimeChart
                label="融券餘額"
                format="lots"
                series={[{ name: "融券", kind: "line", color: "--series-2", data: points(recent, (d) => d.shortBalance) }]}
              />
            </CardContent>
          </Card>
        ) : null}
        {hasHoldings ? (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">外資持股比</CardTitle>
              {summary?.foreignRatio != null ? (
                <CardDescription className="tabular-nums">
                  {formatValue(summary.foreignRatio, "percent")}
                  {summary.foreignRatioChange20d !== null
                    ? `，20 日 ${pointChange(summary.foreignRatioChange20d)}`
                    : ""}
                </CardDescription>
              ) : null}
            </CardHeader>
            <CardContent>
              <TimeChart
                label="外資持股比"
                format="percent"
                series={[{ name: "持股比", kind: "line", color: "--series-1", data: points(recent, (d) => d.foreignRatio) }]}
              />
            </CardContent>
          </Card>
        ) : null}
        <HoldersCard weeks={weeks} summary={summary} />
      </div>

      {rows.length > 0 ? <ChipTable rows={rows.slice(-TABLE_DAYS)} /> : null}
    </section>
  );
}

/** Fraction-point change as percentage points ("+0.35 個百分點"). */
function pointChange(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value * 100).toFixed(2)} 個百分點`;
}

function SummaryTiles({ summary }: { summary: ChipSummary }) {
  const groups = [
    { label: "外資", streak: summary.foreignStreak, d5: summary.foreignNet5d, d20: summary.foreignNet20d },
    { label: "投信", streak: summary.trustStreak, d5: summary.trustNet5d, d20: summary.trustNet20d },
    { label: "自營商", streak: summary.dealerStreak, d5: summary.dealerNet5d, d20: summary.dealerNet20d },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {groups.map((g) => (
        <Card key={g.label} size="sm">
          <CardContent className="space-y-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium">{g.label}</span>
              <span className={cn("text-xs tabular-nums", directionClass(g.streak))}>{streakLabel(g.streak)}</span>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
              <dt className="text-muted-foreground">5 日</dt>
              <dd className="text-right">
                <Lots shares={g.d5} /> 張
              </dd>
              <dt className="text-muted-foreground">20 日</dt>
              <dd className="text-right">
                <Lots shares={g.d20} /> 張
              </dd>
            </dl>
          </CardContent>
        </Card>
      ))}
      <Card size="sm">
        <CardContent className="space-y-1">
          <span className="text-sm font-medium">三大法人</span>
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
            <dt className="text-muted-foreground">5 日</dt>
            <dd className="text-right">
              <Lots shares={summary.totalNet5d} /> 張
            </dd>
            <dt className="text-muted-foreground">占成交量</dt>
            <dd className="text-right tabular-nums">{formatValue(summary.totalVolumeRatio5d, "percent")}</dd>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function HoldersCard({ weeks, summary }: { weeks: HolderWeek[]; summary: ChipSummary | null }) {
  const latest = weeks.at(-1);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm">集保大戶持股比（每週）</CardTitle>
        {latest ? (
          <CardDescription className="tabular-nums">
            {periodLabel(latest.week, "day")}：400 張以上 {formatValue(latest.bigHolderRatio, "percent")}
            {summary?.bigHolderChange1w != null ? `（週 ${pointChange(summary.bigHolderChange1w)}）` : ""}，千張以上{" "}
            {formatValue(latest.whaleRatio, "percent")}
            {latest.holders !== null ? `，股東 ${latest.holders.toLocaleString("zh-TW")} 人` : ""}
          </CardDescription>
        ) : (
          <CardDescription>集保資料從 2026-10 開始每週累積。</CardDescription>
        )}
      </CardHeader>
      {weeks.length > 1 ? (
        <CardContent>
          <TimeChart
            label="大戶持股比"
            format="percent"
            series={[
              { name: "400 張以上", kind: "line", color: "--series-1", data: weeks.map((w) => ({ time: w.week, value: w.bigHolderRatio })) },
              { name: "千張以上", kind: "line", color: "--series-2", data: weeks.map((w) => ({ time: w.week, value: w.whaleRatio })) },
            ]}
          />
        </CardContent>
      ) : weeks.length === 1 ? (
        <CardContent className="text-xs text-muted-foreground">累積兩週以上才會畫出走勢。</CardContent>
      ) : null}
    </Card>
  );
}

function ChipTable({ rows }: { rows: ChipDay[] }) {
  const body = [...rows].reverse().map((d) => (
    <TableRow key={d.date}>
      <TableCell className="sticky left-0 bg-background tabular-nums">{d.date}</TableCell>
      <TableCell className="text-right">
        <Lots shares={d.foreignNet} />
      </TableCell>
      <TableCell className="text-right">
        <Lots shares={d.trustNet} />
      </TableCell>
      <TableCell className="text-right">
        <Lots shares={d.dealerNet} />
      </TableCell>
      <TableCell className="text-right">
        <Lots shares={d.totalNet} />
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {d.marginBalance === null ? "—" : Math.round(d.marginBalance / 1000).toLocaleString("zh-TW")}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {d.shortBalance === null ? "—" : Math.round(d.shortBalance / 1000).toLocaleString("zh-TW")}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {d.foreignRatio === null ? "—" : `${(d.foreignRatio * 100).toFixed(2)}%`}
      </TableCell>
    </TableRow>
  ));
  return (
    <section aria-labelledby="chip-days" className="space-y-2">
      <h3 id="chip-days" className="text-sm font-medium">
        每日明細（張）
      </h3>
      <div className="overflow-x-auto rounded-lg border">
        <Table className="min-w-[40rem] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="sticky left-0 bg-background">日期</TableHead>
              <TableHead className="text-right">外資</TableHead>
              <TableHead className="text-right">投信</TableHead>
              <TableHead className="text-right">自營商</TableHead>
              <TableHead className="text-right">合計</TableHead>
              <TableHead className="text-right">融資餘額</TableHead>
              <TableHead className="text-right">融券餘額</TableHead>
              <TableHead className="text-right">外資持股</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <ShowMoreRows rows={body} initial={TABLE_ROWS} colSpan={8} />
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
