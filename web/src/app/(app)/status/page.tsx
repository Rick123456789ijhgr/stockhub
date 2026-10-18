import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
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
import { AutoRefresh } from "@/components/status/auto-refresh";
import {
  BackfillCard,
  StatTiles,
  YearBars,
  YearCoverage,
} from "@/components/status/data-progress";
import { getDataTotals, getDayCoverage, getRunningBackfills, taipeiToday } from "@/lib/coverage";
import { fetchedRange, summarizeYears } from "@/lib/coverage-grid";
import { getDb } from "@/lib/db";
import { formatDuration, formatInteger, formatTaipeiDateTime } from "@/lib/format";
import { getStatusData, type JobRunRow, type JobRunStatus } from "@/lib/status";

export const metadata: Metadata = { title: "資料狀態" };

const STATUS_LABEL: Record<JobRunStatus, string> = {
  running: "執行中",
  succeeded: "成功",
  failed: "失敗",
  skipped: "略過",
};

const STATUS_VARIANT: Record<JobRunStatus, "secondary" | "destructive" | "outline"> = {
  running: "outline",
  succeeded: "secondary",
  failed: "destructive",
  skipped: "outline",
};

export default function StatusPage({ searchParams }: PageProps<"/status">) {
  return (
    <>
      <PageHeader title="資料狀態" description="資料抓取進度、每日涵蓋與任務紀錄（時間為台北時間）。" />
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <StatusContent searchParams={searchParams} />
      </Suspense>
    </>
  );
}

// Layouts and pages render in parallel, so the page checks the session itself before
// touching data (the layout gate and the proxy are not enough on their own).
async function StatusContent({ searchParams }: { searchParams: PageProps<"/status">["searchParams"] }) {
  await requireUser();
  const db = getDb();
  const today = taipeiToday();
  const thisYear = Number(today.slice(0, 4));
  const [{ jobRuns }, days, totals, backfills, params] = await Promise.all([
    getStatusData(db),
    getDayCoverage(db, thisYear),
    getDataTotals(db),
    getRunningBackfills(db),
    searchParams,
  ]);

  const pending = backfills.map((b) => ({ from: b.next ?? b.start, to: b.end }));
  const years = summarizeYears(days, today, pending);
  const range = fetchedRange(days);
  const requested = Number(Array.isArray(params.year) ? params.year[0] : params.year);
  const selectedYear = years.some((y) => y.year === requested)
    ? requested
    : Number((range?.last ?? today).slice(0, 4));
  const coveredDays = years.reduce((sum, y) => sum + y.fetched + y.partial, 0);
  const running = backfills.length > 0 || jobRuns.some((r) => r.status === "running");

  return (
    <>
      <AutoRefresh seconds={running ? 5 : 60} />

      <section aria-labelledby="totals" className="mb-6">
        <h2 id="totals" className="sr-only">
          總覽
        </h2>
        <StatTiles totals={totals} coveredDays={coveredDays} latest={range?.last ?? null} />
      </section>

      {backfills.length > 0 ? (
        <section aria-labelledby="running" className="mb-6 space-y-3">
          <h2 id="running" className="text-base font-semibold">
            進行中（每 5 秒自動更新）
          </h2>
          {backfills.map((run) => (
            <BackfillCard key={run.id} run={run} now={new Date()} />
          ))}
        </section>
      ) : null}

      <section aria-labelledby="coverage" className="mb-6">
        <Card>
          <CardHeader>
            <CardTitle id="coverage" className="text-base">
              日線涵蓋
            </CardTitle>
            <CardDescription>
              每年已抓取的交易日（深色：上市、上櫃都有；淺色：只有一個市場）。點年份看每日明細。
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <YearBars years={years} selected={selectedYear} />
            <div>
              <h3 className="mb-2 text-sm font-medium">{selectedYear} 年每日涵蓋</h3>
              <YearCoverage year={selectedYear} days={days} today={today} pending={pending} />
            </div>
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="job-runs">
        <h2 id="job-runs" className="mb-3 text-base font-semibold">
          最近的任務紀錄
        </h2>
        {jobRuns.length === 0 ? (
          <Card>
            <CardContent className="text-sm text-muted-foreground">
              尚無任務紀錄。執行 <code className="font-mono">make etl-heartbeat</code> 試試看。
            </CardContent>
          </Card>
        ) : (
          <>
            <JobRunCards runs={jobRuns} />
            <JobRunTable runs={jobRuns} />
          </>
        )}
      </section>
    </>
  );
}

function StatusBadge({ status }: { status: JobRunStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

/** Mobile: one card per run. */
function JobRunCards({ runs }: { runs: JobRunRow[] }) {
  return (
    <ul className="space-y-2 md:hidden">
      {runs.map((run) => (
        <li key={run.id}>
          <Card size="sm">
            <CardContent className="space-y-1 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{run.jobName}</span>
                <StatusBadge status={run.status} />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
                <span>{formatTaipeiDateTime(run.startedAt)}</span>
                <span>
                  {formatDuration(run.durationMs)} · {formatInteger(run.rowsWritten)} 筆
                </span>
              </div>
              {run.errorSummary ? (
                <p className="break-words text-xs text-destructive">{run.errorSummary}</p>
              ) : null}
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

/** Desktop: full table. */
function JobRunTable({ runs }: { runs: JobRunRow[] }) {
  return (
    <div className="hidden rounded-lg border md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>任務</TableHead>
            <TableHead>狀態</TableHead>
            <TableHead>開始時間</TableHead>
            <TableHead className="text-right">耗時</TableHead>
            <TableHead className="text-right">筆數</TableHead>
            <TableHead>觸發</TableHead>
            <TableHead>錯誤摘要</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              <TableCell className="font-medium">{run.jobName}</TableCell>
              <TableCell>
                <StatusBadge status={run.status} />
              </TableCell>
              <TableCell className="tabular-nums">{formatTaipeiDateTime(run.startedAt)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatDuration(run.durationMs)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatInteger(run.rowsWritten)}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {run.trigger === "schedule" ? "排程" : "手動"}
              </TableCell>
              <TableCell className="max-w-80 truncate text-destructive" title={run.errorSummary ?? ""}>
                {run.errorSummary ?? ""}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
