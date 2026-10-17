/** Display-layer formatting. Storage is UTC / Taipei trading dates; convert only here. */

const TAIPEI_DATETIME = new Intl.DateTimeFormat("zh-TW", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** "2026/10/18 09:05:03" in Asia/Taipei. */
export function formatTaipeiDateTime(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  return TAIPEI_DATETIME.format(date);
}

/** Human duration: 850 ms, 12.3 s, 4 分 05 秒, 1 小時 02 分. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  return hours > 0
    ? `${hours} 小時 ${String(minutes).padStart(2, "0")} 分`
    : `${minutes} 分 ${String(secs).padStart(2, "0")} 秒`;
}

/** An error collapsed onto one line and truncated for tables. */
export function summarizeError(error: string | null | undefined, max = 120): string | null {
  const line = error
    ?.split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join(" ");
  if (!line) return null;
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

export function formatInteger(value: number | string | null | undefined): string {
  if (value == null || value === "") return "—";
  return new Intl.NumberFormat("zh-TW").format(Number(value));
}
