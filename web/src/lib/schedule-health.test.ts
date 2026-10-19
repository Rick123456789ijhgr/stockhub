import { describe, expect, it } from "vitest";

import { lastOccurrence, SCHEDULES, type ScheduleRun, scheduleHealth } from "./schedule-health";

const [QUOTES, DAILY] = SCHEDULES;

/** Taipei wall-clock time as a Date. */
function taipei(iso: string): Date {
  return new Date(`${iso}+08:00`);
}

function run(jobName: string, startedAt: string, status: ScheduleRun["status"] = "succeeded", error: string | null = null): ScheduleRun {
  const start = taipei(startedAt);
  return {
    jobName,
    status,
    startedAt: start.toISOString(),
    finishedAt: status === "running" ? null : new Date(start.getTime() + 60_000).toISOString(),
    errorSummary: error,
  };
}

describe("lastOccurrence", () => {
  it("is today once the time has passed, else the previous weekday", () => {
    // 2026-10-19 is a Monday.
    expect(lastOccurrence(taipei("2026-10-19T09:00:00"), "08:55")).toEqual(taipei("2026-10-19T08:55:00"));
    expect(lastOccurrence(taipei("2026-10-19T08:00:00"), "08:55")).toEqual(taipei("2026-10-16T08:55:00"));
    expect(lastOccurrence(taipei("2026-10-18T12:00:00"), "18:00")).toEqual(taipei("2026-10-16T18:00:00"));
  });

  it("works across the UTC date line", () => {
    // 07:00 Taipei on Tuesday is 23:00 UTC on Monday.
    expect(lastOccurrence(taipei("2026-10-20T07:00:00"), "18:00")).toEqual(taipei("2026-10-19T18:00:00"));
  });
});

describe("scheduleHealth", () => {
  it("is pending right after the scheduled time and missed after the grace period", () => {
    expect(scheduleHealth(QUOTES, [], taipei("2026-10-19T09:05:00")).state).toBe("pending");
    expect(scheduleHealth(QUOTES, [], taipei("2026-10-19T09:30:00")).state).toBe("missed");
  });

  it("ignores runs from before this occurrence", () => {
    const runs = [run("poll_quotes", "2026-10-16T08:55:01")];
    const health = scheduleHealth(QUOTES, runs, taipei("2026-10-19T10:00:00"));
    expect(health.state).toBe("missed");
    expect(health.lastCompletedAt).toBe(taipei("2026-10-16T08:56:01").toISOString());
  });

  it("follows a multi-job run to completion", () => {
    const now = taipei("2026-10-19T18:10:00");
    const started = [run("sync_calendar", "2026-10-19T18:00:02"), run("sync_stocks", "2026-10-19T18:01:00", "running")];
    expect(scheduleHealth(DAILY, started, now)).toMatchObject({ state: "running", job: "sync_stocks" });
    const finished = [
      ...DAILY.jobs.map((job, i) => run(job, `2026-10-19T18:0${i}:00`)),
    ];
    expect(scheduleHealth(DAILY, finished, now).state).toBe("ok");
  });

  it("reports the failed job with its error", () => {
    const runs = [run("sync_calendar", "2026-10-19T18:00:02"), run("sync_stocks", "2026-10-19T18:01:00", "failed", "HTTP 503")];
    expect(scheduleHealth(DAILY, runs, taipei("2026-10-19T19:00:00"))).toMatchObject({
      state: "failed",
      job: "sync_stocks",
      error: "HTTP 503",
    });
  });

  it("settles a failure that a later rerun of the same job fixed", () => {
    const runs = [
      run("poll_quotes", "2026-10-19T08:55:01", "failed", "boom"),
      run("poll_quotes", "2026-10-19T09:10:00"),
    ];
    expect(scheduleHealth(QUOTES, runs, taipei("2026-10-19T14:00:00")).state).toBe("ok");
  });

  it("counts a skipped run (market holiday) as done", () => {
    const runs = [run("poll_quotes", "2026-10-19T08:55:01", "skipped")];
    expect(scheduleHealth(QUOTES, runs, taipei("2026-10-19T12:00:00")).state).toBe("ok");
  });

  it("flags a run that stopped part way without failing", () => {
    const runs = [run("sync_calendar", "2026-10-19T18:00:02")];
    expect(scheduleHealth(DAILY, runs, taipei("2026-10-19T18:30:00")).state).toBe("running");
    expect(scheduleHealth(DAILY, runs, taipei("2026-10-19T22:00:00")).state).toBe("incomplete");
  });
});
