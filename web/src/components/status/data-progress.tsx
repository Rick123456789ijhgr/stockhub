import { TriangleAlert } from "lucide-react";
import Link from "next/link";

import { JobButton } from "@/components/jobs/job-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { DataTotals, RunningBackfill } from "@/lib/coverage";
import {
  backfillProgress,
  type DayCoverage,
  fetchedRange,
  type Pending,
  gapDays,
  type YearSummary,
  yearGrid,
} from "@/lib/coverage-grid";
import { formatInteger, formatTaipeiDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CoverageGrid, CoverageLegend } from "./coverage-grid";

export function StatTiles({
  totals,
  coveredDays,
  latest,
}: {
  totals: DataTotals;
  coveredDays: number;
  latest: string | null;
}) {
  const tiles = [
    { label: "日線筆數", value: formatInteger(totals.bars) },
    { label: "已涵蓋交易日", value: formatInteger(coveredDays) },
    { label: "最新資料日", value: latest ?? "尚無" },
    { label: "股票／ETF", value: `${formatInteger(totals.stocks)}／${formatInteger(totals.etfs)}` },
    {
      label: "待處理隔離",
      value: formatInteger(totals.quarantinePending),
      warn: totals.quarantinePending > 0,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {tiles.map((tile) => (
        <Card key={tile.label} size="sm">
          <CardHeader>
            <CardDescription className="flex items-center gap-1">
              {tile.warn ? <TriangleAlert className="size-3.5" aria-label="需要處理" /> : null}
              {tile.label}
            </CardDescription>
            <CardTitle className="text-xl group-data-[size=sm]/card:text-xl">{tile.value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

function formatEta(seconds: number | null): string {
  if (seconds === null) return "計算中";
  if (seconds < 60) return `約 ${seconds} 秒`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `約 ${minutes} 分鐘` : `約 ${(minutes / 60).toFixed(1)} 小時`;
}

export function BackfillCard({ run, now }: { run: RunningBackfill; now: Date }) {
  const p = backfillProgress(run.tradingDays, run.next, run.startedAt, now);
  return (
    <Card>
      <CardHeader>
        <CardDescription>
          回填進行中（job_runs #{run.id}）：{run.start}～{run.end}
        </CardDescription>
        <CardTitle className="text-3xl">{p.percent.toFixed(0)}%</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div
          className="h-2 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={p.total}
          aria-valuenow={p.done}
          aria-label="回填進度"
        >
          <div className="h-full rounded-full bg-coverage-full" style={{ width: `${p.percent}%` }} />
        </div>
        <p className="text-sm text-muted-foreground tabular-nums">
          {formatInteger(p.done)} / {formatInteger(p.total)} 個交易日
          {run.next ? `，下一天 ${run.next}` : ""}，剩餘 {formatEta(p.etaSeconds)}，開始於{" "}
          {formatTaipeiDateTime(run.startedAt)}
        </p>
      </CardContent>
    </Card>
  );
}

/** One bar per year with data; years not backfilled yet collapse into one line. */
export function YearBars({
  years,
  selected,
}: {
  years: YearSummary[];
  selected: number;
}) {
  const withData = years.filter((y) => y.fetched + y.partial + y.gaps > 0);
  const empty = years.filter((y) => y.fetched + y.partial + y.gaps === 0 && y.tradingDays > 0);
  const emptyDays = empty.reduce((sum, y) => sum + y.tradingDays, 0);

  return (
    <div className="space-y-1.5">
      {withData.map((y) => {
        const full = y.tradingDays ? (y.fetched / y.tradingDays) * 100 : 0;
        const partial = y.tradingDays ? (y.partial / y.tradingDays) * 100 : 0;
        return (
          <Link
            key={y.year}
            href={`/status?year=${y.year}`}
            scroll={false}
            aria-current={y.year === selected ? "true" : undefined}
            className={cn(
              "grid grid-cols-[3rem_1fr_auto] items-center gap-3 rounded-md px-2 py-1 text-sm hover:bg-muted",
              y.year === selected && "bg-muted font-medium",
            )}
          >
            <span className="tabular-nums">{y.year}</span>
            <span className="flex h-2.5 gap-[2px] overflow-hidden rounded-full bg-muted" aria-hidden>
              {full > 0 ? <span className="h-full rounded-full bg-coverage-full" style={{ width: `${full}%` }} /> : null}
              {partial > 0 ? (
                <span className="h-full rounded-full bg-coverage-partial" style={{ width: `${partial}%` }} />
              ) : null}
            </span>
            <span className="flex items-center gap-1 text-xs text-muted-foreground tabular-nums">
              {y.gaps > 0 ? <TriangleAlert className="size-3.5" aria-label={`${y.gaps} 天缺漏`} /> : null}
              {y.fetched} / {y.tradingDays} 天（{full.toFixed(0)}%）
            </span>
          </Link>
        );
      })}
      {empty.length > 0 ? (
        <p className="px-2 pt-1 text-xs text-muted-foreground">
          {empty[empty.length - 1].year}–{empty[0].year} 尚未回填，共約 {formatInteger(emptyDays)}{" "}
          個交易日（以 <code>make etl-backfill start=YYYY-MM-DD</code> 補上）
        </p>
      ) : null}
    </div>
  );
}

export function YearCoverage({
  year,
  days,
  today,
  pending,
}: {
  year: number;
  days: DayCoverage[];
  today: string;
  pending: Pending;
}) {
  const range = fetchedRange(days);
  const rows = yearGrid(
    year,
    days.filter((d) => d.date.startsWith(`${year}-`)),
    today,
    range,
    pending,
  );
  const problems = gapDays(days, today, pending).filter((d) => d.date.startsWith(`${year}-`));

  return (
    <div className="space-y-3">
      <CoverageGrid rows={rows} />
      <CoverageLegend />
      {problems.length > 0 ? (
        <div className="rounded-lg border p-3">
          <p className="mb-2 flex items-center gap-1.5 text-sm font-medium">
            <TriangleAlert className="size-4" aria-hidden />
            需要注意的日期（{problems.length}）
          </p>
          <ul className="grid grid-cols-1 gap-2 text-sm tabular-nums sm:grid-cols-2">
            {problems.map((d) => (
              <li key={d.date} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>
                  {d.date}：
                  {d.twse + d.tpex === 0 ? "缺漏" : `只有${d.twse > 0 ? "上市" : "上櫃"}資料`}
                </span>
                <JobButton
                  size="xs"
                  label="重新抓取"
                  requests={[{ job: "daily_prices", params: { date: d.date } }]}
                />
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            交易所當天沒有資料（例如颱風臨時休市）時，重新抓取會把這天改標為休市。
          </p>
        </div>
      ) : null}
    </div>
  );
}
