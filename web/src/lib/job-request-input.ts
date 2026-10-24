/**
 * Validation of jobs the site may queue (job_requests). Mirrors the CHECK on
 * job_requests.job_name; the Python jobs validate their params again.
 */

export const REQUESTABLE_JOBS = [
  "daily_prices",
  "catch_up_prices",
  "refetch_stock_prices",
  "refresh_stock_fundamentals",
  "sync_chips",
  "sync_markets",
  "sync_macro",
  "sync_news",
  "check_llm_providers",
] as const;

export type RequestableJob = (typeof REQUESTABLE_JOBS)[number];

export type JobRequestInput = { job: RequestableJob; params: Record<string, string> };

export const JOB_LABEL: Record<RequestableJob, string> = {
  daily_prices: "重新抓取日線",
  catch_up_prices: "日線更新到今天",
  refetch_stock_prices: "補抓個股缺漏日線",
  refresh_stock_fundamentals: "重新抓取財報與月營收",
  sync_chips: "籌碼更新到今天",
  sync_markets: "市場更新到今天",
  sync_macro: "總經指標更新",
  sync_news: "新聞與社群更新",
  check_llm_providers: "檢查 LLM 服務",
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const SYMBOL = /^[0-9A-Z]{4,6}$/;
const FIRST_PRICE_DATE = "2004-02-11";

function isRealDate(value: string): boolean {
  if (!DATE.test(value)) return false;
  const d = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value;
}

/** A queueable request, or null. `today` is the Taipei date (YYYY-MM-DD). */
export function parseJobRequest(body: unknown, today: string): JobRequestInput | null {
  if (typeof body !== "object" || body === null) return null;
  const { job, params } = body as { job?: unknown; params?: unknown };
  if (typeof job !== "string" || !(REQUESTABLE_JOBS as readonly string[]).includes(job)) {
    return null;
  }
  const raw = (typeof params === "object" && params !== null ? params : {}) as Record<
    string,
    unknown
  >;
  switch (job as RequestableJob) {
    case "daily_prices": {
      const date = raw.date;
      if (typeof date !== "string" || !isRealDate(date)) return null;
      if (date < FIRST_PRICE_DATE || date > today) return null;
      return { job: "daily_prices", params: { date } };
    }
    case "catch_up_prices":
    case "sync_chips":
    case "sync_markets":
    case "sync_macro":
    case "sync_news":
    case "check_llm_providers":
      return { job: job as RequestableJob, params: {} };
    case "refetch_stock_prices":
    case "refresh_stock_fundamentals": {
      const symbol = typeof raw.symbol === "string" ? raw.symbol.trim().toUpperCase() : "";
      if (!SYMBOL.test(symbol)) return null;
      return { job: job as RequestableJob, params: { symbol } };
    }
  }
}
