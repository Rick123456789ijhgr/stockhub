import "server-only";

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

import { isLocalMachine } from "@/lib/auth/mode";

/**
 * Starts `make etl-requests` (python -m stockhub.etl drain-requests) in the background so a
 * request queued from the site runs right away. Only with JOB_RUNNER=local, and never on
 * Vercel or in a deployed production build (`isLocalMachine`): there nothing can run Python,
 * and requests wait for the next scheduled etl-daily (which drains the queue first).
 *
 * Runs through scripts/scheduled.sh, so it gets the same tool PATH, database start-up and
 * daily log file (.local/logs/etl-requests-YYYYMMDD.log) as the scheduled jobs.
 */
export type RunnerResult = "started" | "queued";

export function runnerEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.JOB_RUNNER === "local" && isLocalMachine(env);
}

function repoRoot(): string | null {
  // next.mjs runs Next.js from web/; tests may run elsewhere.
  for (const candidate of [path.resolve(process.cwd(), ".."), process.cwd()]) {
    if (existsSync(path.join(candidate, "scripts", "scheduled.sh"))) return candidate;
  }
  return null;
}

function bashPath(env: NodeJS.ProcessEnv): string {
  if (env.JOB_RUNNER_BASH) return env.JOB_RUNNER_BASH;
  return process.platform === "win32" ? "C:\\Program Files\\Git\\bin\\bash.exe" : "bash";
}

export function startDrainer(env: NodeJS.ProcessEnv = process.env): RunnerResult {
  if (!runnerEnabled(env)) return "queued";
  const root = repoRoot();
  const bash = bashPath(env);
  if (!root || (process.platform === "win32" && !existsSync(bash))) return "queued";
  try {
    const child = spawn(bash, ["-l", "scripts/scheduled.sh", "etl-requests"], {
      cwd: root,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    });
    child.on("error", (err) => console.error("job runner failed to start", err));
    child.unref();
    return "started";
  } catch (err) {
    console.error("job runner failed to start", err);
    return "queued";
  }
}
