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

export default function StatusPage() {
  return (
    <>
      <PageHeader title="資料狀態" description="排程任務紀錄與各資料集的最新日期（時間為台北時間）。" />
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <StatusContent />
      </Suspense>
    </>
  );
}

// Layouts and pages render in parallel, so the page checks the session itself before
// touching data (the layout gate and the proxy are not enough on their own).
async function StatusContent() {
  await requireUser();
  const { jobRuns, datasets } = await getStatusData(getDb());

  return (
    <>

      <section aria-labelledby="datasets" className="mb-6">
        <h2 id="datasets" className="sr-only">
          資料集
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {datasets.map((d) => (
            <Card key={d.dataset} size="sm">
              <CardHeader>
                <CardDescription>
                  {d.label}
                  <span className="ml-1 font-mono text-xs">({d.dataset})</span>
                </CardDescription>
                <CardTitle className="text-lg tabular-nums">
                  {d.latestDate ?? <span className="text-muted-foreground">尚無資料</span>}
                </CardTitle>
              </CardHeader>
            </Card>
          ))}
        </div>
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
