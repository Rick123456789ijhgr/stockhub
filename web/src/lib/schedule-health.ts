/**
 * Health of the scheduled runs (scripts/register-tasks.ps1), judged from job_runs against
 * when each schedule should last have fired. A run that never started (PC off, Postgres
 * down, task disabled) leaves no job_runs row, so "missed" is only visible this way.
 */

export type ScheduleRun = {
  jobName: string;
  status: "running" | "succeeded" | "failed" | "skipped";
  startedAt: string;
  finishedAt: string | null;
  errorSummary: string | null;
};

export type Schedule = {
  key: string;
  label: string;
  command: string;
  /** Taipei wall-clock time on weekdays (the task fires Mon–Fri; jobs skip holidays). */
  time: string;
  /** Jobs the command runs, in order; the last one finishing means the run is done. */
  jobs: readonly string[];
  /** Minutes after the scheduled time before a run that has not started counts as missed. */
  graceMinutes: number;
  /** Minutes after the scheduled time after which an unfinished run counts as incomplete. */
  maxMinutes: number;
};

export const SCHEDULES: readonly Schedule[] = [
  {
    key: "quotes",
    label: "盤中報價",
    command: "make etl-quotes",
    time: "08:55",
    jobs: ["poll_quotes"],
    graceMinutes: 20,
    maxMinutes: 300,
  },
  {
    key: "daily",
    label: "每日更新",
    command: "make etl-daily",
    time: "18:00",
    jobs: [
      "sync_calendar",
      "sync_stocks",
      "sync_delistings",
      "sync_corporate_actions",
      "sync_dividend_details",
      "daily_prices",
      "compute_adj_factors",
    ],
    graceMinutes: 30,
    maxMinutes: 180,
  },
  {
    key: "chips",
    label: "籌碼（晚間）",
    command: "make etl-chips",
    time: "21:30",
    jobs: ["sync_chips", "compute_chip_summary"],
    graceMinutes: 30,
    maxMinutes: 60,
  },
];

export type ScheduleState = "ok" | "running" | "pending" | "failed" | "missed" | "incomplete";

export type ScheduleHealth = {
  schedule: Schedule;
  state: ScheduleState;
  /** When the schedule should last have fired (ISO, UTC). */
  expectedAt: string;
  /** The failed job, or the last job that ran, in this occurrence. */
  job: string | null;
  error: string | null;
  /** Latest finish of the schedule's last job, at any time (ISO). */
  lastCompletedAt: string | null;
};

const TAIPEI_OFFSET_MS = 8 * 60 * 60 * 1000; // UTC+8, no daylight saving
const MINUTE = 60 * 1000;

/** The latest weekday `time` (Taipei) at or before `now`. */
export function lastOccurrence(now: Date, time: string): Date {
  const [hours, minutes] = time.split(":").map(Number);
  const local = new Date(now.getTime() + TAIPEI_OFFSET_MS); // Taipei wall clock in UTC fields
  const candidate = new Date(
    Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), hours, minutes),
  );
  while (candidate > local || candidate.getUTCDay() === 0 || candidate.getUTCDay() === 6) {
    candidate.setUTCDate(candidate.getUTCDate() - 1);
  }
  return new Date(candidate.getTime() - TAIPEI_OFFSET_MS);
}

/** State of one schedule at `now` from recent runs of its jobs (any order). */
export function scheduleHealth(schedule: Schedule, runs: readonly ScheduleRun[], now: Date): ScheduleHealth {
  const expected = lastOccurrence(now, schedule.time);
  const finalJob = schedule.jobs[schedule.jobs.length - 1];
  const mine = runs.filter((r) => schedule.jobs.includes(r.jobName));
  // A task started a few minutes early (clock skew) or late (StartWhenAvailable) still counts.
  const window = mine
    .filter((r) => new Date(r.startedAt).getTime() >= expected.getTime() - 5 * MINUTE)
    .sort((a, b) => a.startedAt.localeCompare(b.startedAt));
  const lastCompletedAt =
    mine
      .filter((r) => r.jobName === finalJob && r.status !== "failed" && r.status !== "running")
      .map((r) => r.finishedAt ?? r.startedAt)
      .sort()
      .at(-1) ?? null;
  const base = { schedule, expectedAt: expected.toISOString(), lastCompletedAt };
  const elapsed = (now.getTime() - expected.getTime()) / MINUTE;

  if (window.length === 0) {
    const state = elapsed < schedule.graceMinutes ? "pending" : "missed";
    return { ...base, state, job: null, error: null };
  }
  // A failure that a later run of the same job recovered from (a manual rerun) is settled.
  const failed = window.find(
    (r) =>
      r.status === "failed" &&
      !window.some(
        (later) =>
          later.jobName === r.jobName &&
          later.startedAt > r.startedAt &&
          (later.status === "succeeded" || later.status === "skipped"),
      ),
  );
  if (failed) return { ...base, state: "failed", job: failed.jobName, error: failed.errorSummary };
  const last = window[window.length - 1];
  const done = window.some((r) => r.jobName === finalJob && r.status !== "running");
  if (done) return { ...base, state: "ok", job: last.jobName, error: null };
  if (window.some((r) => r.status === "running") || elapsed < schedule.maxMinutes) {
    return { ...base, state: "running", job: last.jobName, error: null };
  }
  return { ...base, state: "incomplete", job: last.jobName, error: null };
}
