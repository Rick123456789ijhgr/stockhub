/** Display-layer formatting. Storage is UTC / Taipei trading dates; convert only here. */

const TAIPEI_DATETIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/**
 * "2026/10/18 09:05:03" in Asia/Taipei. Assembled from parts because ICU versions differ
 * in the separators and invisible marks they emit for zh-TW.
 */
export function formatTaipeiDateTime(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const date = typeof value === "string" ? new Date(value) : value;
  const part = Object.fromEntries(
    TAIPEI_DATETIME.formatToParts(date).map((p) => [p.type, p.value]),
  ) as Record<Intl.DateTimeFormatPartTypes, string>;
  return `${part.year}/${part.month}/${part.day} ${part.hour}:${part.minute}:${part.second}`;
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

// Formatters are created once: building an Intl.NumberFormat costs far more than using it,
// and long lists call these thousands of times per render.
const INTEGER = new Intl.NumberFormat("zh-TW");
const FIXED = new Map<number, Intl.NumberFormat>();
const LOTS = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function fixed(digits: number): Intl.NumberFormat {
  let f = FIXED.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    FIXED.set(digits, f);
  }
  return f;
}

export function formatInteger(value: number | string | null | undefined): string {
  if (value == null || value === "") return "—";
  return INTEGER.format(Number(value));
}

/** Price string from the DB ("2420.0000") -> "2,420.00"; null -> "—". */
export function formatPrice(value: string | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return fixed(digits).format(Number(value));
}

/** Shares -> lots (張, 1,000 shares), the unit Taiwanese quotes are read in. */
export function formatLots(shares: string | number | null | undefined): string {
  if (shares == null || shares === "") return "—";
  return LOTS.format(Math.round(Number(shares) / 1000));
}

/** TWD -> 億 (100 million) with two decimals. */
export function formatHundredMillion(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  return fixed(2).format(Number(value) / 1e8);
}
