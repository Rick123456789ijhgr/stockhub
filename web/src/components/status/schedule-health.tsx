import { AlertTriangle, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatTaipeiDateTime } from "@/lib/format";
import type { ScheduleHealth, ScheduleState } from "@/lib/schedule-health";

const STATE: Record<
  ScheduleState,
  { label: string; variant: "secondary" | "outline" | "destructive"; Icon: typeof Clock }
> = {
  ok: { label: "已完成", variant: "secondary", Icon: CheckCircle2 },
  running: { label: "執行中", variant: "outline", Icon: Loader2 },
  pending: { label: "即將執行", variant: "outline", Icon: Clock },
  failed: { label: "失敗", variant: "destructive", Icon: XCircle },
  missed: { label: "未執行", variant: "destructive", Icon: AlertTriangle },
  incomplete: { label: "未跑完", variant: "destructive", Icon: AlertTriangle },
};

function detail(h: ScheduleHealth): string {
  const at = formatTaipeiDateTime(h.expectedAt).slice(0, 16);
  switch (h.state) {
    case "ok":
      return `${at} 的排程已完成。`;
    case "running":
      return `${at} 的排程進行中（目前：${h.job}）。`;
    case "pending":
      return `排程時間 ${at}，等待啟動。`;
    case "failed":
      return `${at} 的排程在 ${h.job} 失敗${h.error ? `：${h.error}` : "。"}`;
    case "missed":
      return `${at} 應該執行，但沒有任何紀錄：電腦可能沒開、沒有登入，或本機 Postgres 沒啟動。記錄在 .local/logs。`;
    case "incomplete":
      return `${at} 的排程停在 ${h.job} 之後，沒有跑完也沒有錯誤紀錄；請看 .local/logs。`;
  }
}

/** Scheduled runs (Windows Task Scheduler) vs what job_runs shows; problems first. */
export function ScheduleHealthCard({ items }: { items: ScheduleHealth[] }) {
  const problems = items.filter((h) => STATE[h.state].variant === "destructive").length;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">排程</CardTitle>
        <CardDescription>
          {problems > 0
            ? `${problems} 個排程需要處理。`
            : "平日依 scripts/register-tasks.ps1 的設定自動執行（台北時間）。"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {items.map((h) => {
            const { label, variant, Icon } = STATE[h.state];
            return (
              <li key={h.schedule.key} className="flex flex-col gap-1 py-2 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{h.schedule.label}</span>
                  <span className="text-muted-foreground">
                    平日 {h.schedule.time} · <code className="font-mono">{h.schedule.command}</code>
                  </span>
                  <Badge variant={variant} className="ml-auto">
                    <Icon aria-hidden className={h.state === "running" ? "animate-spin" : undefined} />
                    {label}
                  </Badge>
                </div>
                <p className="text-muted-foreground">{detail(h)}</p>
                <p className="text-xs text-muted-foreground">
                  上次完成：{h.lastCompletedAt ? formatTaipeiDateTime(h.lastCompletedAt) : "30 天內沒有"}
                </p>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
