import { Badge } from "@/components/ui/badge";
import { formatTaipeiDateTime } from "@/lib/format";
import { JOB_LABEL } from "@/lib/job-request-input";
import type { JobRequestRow, JobRequestStatus } from "@/lib/job-requests";

const STATUS: Record<JobRequestStatus, { label: string; variant: "secondary" | "outline" | "destructive" }> = {
  queued: { label: "排隊中", variant: "outline" },
  running: { label: "執行中", variant: "outline" },
  succeeded: { label: "完成", variant: "secondary" },
  skipped: { label: "略過", variant: "outline" },
  failed: { label: "失敗", variant: "destructive" },
};

export function hasPendingRequest(rows: JobRequestRow[]): boolean {
  return rows.some((r) => r.status === "queued" || r.status === "running");
}

/** Recent site-queued jobs with their outcome. */
export function JobRequestList({ rows, empty }: { rows: JobRequestRow[]; empty?: string }) {
  if (rows.length === 0) {
    return empty ? <p className="text-sm text-muted-foreground">{empty}</p> : null;
  }
  return (
    <ul className="divide-y text-sm">
      {rows.map((r) => (
        <li key={r.id} className="py-2">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Badge variant={STATUS[r.status].variant}>{STATUS[r.status].label}</Badge>
            <span className="font-medium">{JOB_LABEL[r.job] ?? r.job}</span>
            {r.params.date || r.params.symbol ? (
              <span className="font-semibold tabular-nums text-xs">{r.params.date ?? r.params.symbol}</span>
            ) : null}
            <span className="text-xs text-muted-foreground tabular-nums">
              {formatTaipeiDateTime(r.requestedAt)}
            </span>
          </div>
          {r.message ? (
            <p
              className={
                r.status === "failed"
                  ? "mt-1 break-words text-xs text-destructive"
                  : "mt-1 break-words text-xs text-muted-foreground"
              }
            >
              {r.message.length > 300 ? `${r.message.slice(0, 300)}…` : r.message}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
