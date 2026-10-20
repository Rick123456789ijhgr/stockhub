import type { Metadata } from "next";
import { Suspense } from "react";

import { PageHeader } from "@/components/coming-soon";
import { Disclosure } from "@/components/disclosure";
import { ShowMoreList, ShowMoreRows } from "@/components/show-more";
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
import { JobButton } from "@/components/jobs/job-button";
import { hasPendingRequest, JobRequestList } from "@/components/jobs/job-request-list";
import { AutoRefresh } from "@/components/status/auto-refresh";
import { FundamentalsStatusCard } from "@/components/status/fundamentals-status";
import { ScheduleHealthCard } from "@/components/status/schedule-health";
import {
  BackfillCard,
  StatTiles,
  YearBars,
  YearCoverage,
} from "@/components/status/data-progress";
import { getDataTotals, getDayCoverage, getRunningBackfills, taipeiToday } from "@/lib/coverage";
import { fetchedRange, gapDays, summarizeYears } from "@/lib/coverage-grid";
import { getDb } from "@/lib/db";
import { formatDuration, formatInteger, formatTaipeiDateTime } from "@/lib/format";
import { getFundamentalsStatus } from "@/lib/fundamentals-status";
import { listJobRequests } from "@/lib/job-requests";
import { runnerEnabled } from "@/lib/job-runner";
import { SCHEDULES, scheduleHealth } from "@/lib/schedule-health";
import { getScheduleRuns, getStatusData, type JobRunRow, type JobRunStatus } from "@/lib/status";

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
  const [{ jobRuns }, days, totals, backfills, scheduleRuns, requests, fundamentals, params] =
    await Promise.all([
    getStatusData(db),
    getDayCoverage(db, thisYear),
    getDataTotals(db),
    getRunningBackfills(db),
    getScheduleRuns(db),
    listJobRequests(db, { limit: 8 }),
    getFundamentalsStatus(db),
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
  const running =
    backfills.length > 0 ||
    jobRuns.some((r) => r.status === "running") ||
    hasPendingRequest(requests);
  const problems = gapDays(days, today, pending);
  const now = new Date();
  const schedules = SCHEDULES.map((s) => scheduleHealth(s, scheduleRuns, now));
  const failed = jobRuns.filter((r) => r.status === "failed").length;

  return (
    <>
      <AutoRefresh seconds={running ? 5 : 60} />

      <section aria-labelledby="totals" className="mb-3">
        <h2 id="totals" className="sr-only">
          總覽
        </h2>
        <StatTiles totals={totals} coveredDays={coveredDays} latest={range?.last ?? null} />
      </section>

      {backfills.length > 0 ? (
        <section aria-labelledby="running" className="mb-3 space-y-3">
          <h2 id="running" className="text-sm font-semibold">
            進行中（每 5 秒自動更新）
          </h2>
          {backfills.map((run) => (
            <BackfillCard key={run.id} run={run} now={new Date()} />
          ))}
        </section>
      ) : null}

      <div className="mb-3 grid items-start gap-3 lg:grid-cols-2">
        <section aria-label="排程">
          <ScheduleHealthCard items={schedules} />
        </section>
        <section aria-label="財報與月營收">
          <FundamentalsStatusCard status={fundamentals} now={now} />
        </section>
      </div>

      <section aria-labelledby="repair" className="mb-3">
        <Card size="sm">
          <CardHeader>
            <CardTitle id="repair" className="text-sm">
              手動更新與補抓
            </CardTitle>
            <CardDescription>
              {runnerEnabled()
                ? "按下後立即在本機執行，進度顯示在下方。"
                : "這個環境不能直接執行任務：會先排入佇列，在下一次排程（平日 18:00）開頭執行。"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <JobButton
                label="日線更新到今天"
                variant="default"
                requests={[{ job: "catch_up_prices" }]}
              />
              {problems.length > 0 ? (
                <JobButton
                  label={`重新抓取全部缺漏日（${Math.min(problems.length, 30)} 天）`}
                  requests={problems
                    .slice(-30)
                    .map((d) => ({ job: "daily_prices" as const, params: { date: d.date } }))}
                />
              ) : null}
            </div>
            <JobRequestList rows={requests} />
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="coverage" className="mb-3">
        <Card size="sm">
          <CardContent>
            {/* Picking a year reloads with ?year=, so the section stays open then. */}
            <Disclosure
              defaultOpen={params.year !== undefined}
              summary={<span id="coverage">日線涵蓋</span>}
              meta={range ? `${range.first}～${range.last}` : undefined}
            >
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  每年已抓取的交易日（深色：上市、上櫃都有；淺色：只有一個市場）。點年份看每日明細。
                </p>
                <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
                  <YearBars years={years} selected={selectedYear} />
                  <div>
                    <h3 className="mb-2 text-sm font-medium">{selectedYear} 年每日涵蓋</h3>
                    <YearCoverage year={selectedYear} days={days} today={today} pending={pending} />
                  </div>
                </div>
              </div>
            </Disclosure>
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="job-runs">
        <Card size="sm">
          <CardContent>
            <Disclosure
              summary={<span id="job-runs">最近的任務紀錄</span>}
              meta={`${formatInteger(jobRuns.length)} 筆${failed > 0 ? `，${failed} 筆失敗` : ""}`}
            >
              {jobRuns.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  尚無任務紀錄。執行 <code className="font-mono">make etl-heartbeat</code> 試試看。
                </p>
              ) : (
                <>
                  <JobRunCards runs={jobRuns} />
                  <JobRunTable runs={jobRuns} />
                </>
              )}
            </Disclosure>
          </CardContent>
        </Card>
      </section>
    </>
  );
}

function StatusBadge({ status }: { status: JobRunStatus }) {
  return <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}

const RUNS_SHOWN = 15;

/** Mobile: one card per run. */
function JobRunCards({ runs }: { runs: JobRunRow[] }) {
  return (
    <div className="md:hidden">
      <ShowMoreList
        className="space-y-2"
        initial={RUNS_SHOWN}
        step={RUNS_SHOWN}
        items={runs.map((run) => (
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
      />
    </div>
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
          <ShowMoreRows
            initial={RUNS_SHOWN}
            colSpan={7}
            rows={runs.map((run) => (
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
          />
        </TableBody>
      </Table>
    </div>
  );
}
