/**
 * Display of news items (pure): channels, event types, sentiment wording and relative
 * times. Sentiment uses the up/down tokens like prices (rule 10): bullish reads like a rise.
 */

export type Channel = "news" | "announcement" | "social";

export const CHANNEL_LABEL: Record<Channel, string> = {
  news: "新聞",
  announcement: "重大訊息",
  social: "社群",
};

/** Mirrors EVENT_LABELS in py/stockhub/etl/news_analysis.py (short forms for badges). */
export const EVENT_LABEL: Record<string, string> = {
  earnings: "財報",
  revenue: "營收",
  guidance: "展望",
  dividend: "股利",
  capital: "資本",
  order: "訂單",
  product: "產品",
  expansion: "擴產",
  merger: "併購合作",
  management: "經營層",
  legal: "訴訟裁罰",
  analyst: "法人評等",
  institutional: "籌碼",
  macro: "總經",
  market: "盤勢",
  rumor: "傳聞",
  other: "其他",
};

export type Tone = "up" | "down" | "flat";

/** Same cut-offs as the daily counts in engine/sentiment.py (±0.3). */
export function sentimentTone(value: number | null): Tone | null {
  if (value === null || !Number.isFinite(value)) return null;
  if (value >= 0.3) return "up";
  if (value <= -0.3) return "down";
  return "flat";
}

export const TONE_CLASS: Record<Tone, string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-muted-foreground",
};

/** "偏多 +0.62" / "偏空 −0.40" / "中性 +0.10"; null without a score. */
export function sentimentLabel(value: number | null): string | null {
  const tone = sentimentTone(value);
  if (tone === null || value === null) return null;
  const word = tone === "up" ? "偏多" : tone === "down" ? "偏空" : "中性";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "±";
  return `${word} ${sign}${Math.abs(value).toFixed(2)}`;
}

const TAIPEI_PARTS = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function taipeiParts(date: Date): Record<string, string> {
  return Object.fromEntries(TAIPEI_PARTS.formatToParts(date).map((p) => [p.type, p.value]));
}

/** "剛剛", "12 分鐘前", "3 小時前" within a day; "10/23 14:05" this year; else with the year. */
export function relativeTime(iso: string, now: Date): string {
  const at = new Date(iso);
  const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
  if (minutes < 1) return "剛剛";
  if (minutes < 60) return `${minutes} 分鐘前`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} 小時前`;
  const p = taipeiParts(at);
  const sameYear = p.year === taipeiParts(now).year;
  return `${sameYear ? "" : `${p.year}/`}${p.month}/${p.day} ${p.hour}:${p.minute}`;
}

/** The link's host without www (the source of a forum post or article). */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
