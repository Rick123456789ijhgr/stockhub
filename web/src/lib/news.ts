import "server-only";

import { type Kysely, sql } from "kysely";

import type { DB } from "@/lib/db";
import type { Channel } from "@/lib/news-format";
import { loadPortfolio } from "@/lib/portfolio-data";

export type NewsStock = {
  symbol: string;
  name: string;
  relation: "direct" | "industry" | "theme";
  sentiment: number | null;
};

export type NewsListItem = {
  id: string;
  channel: Channel;
  source: string;
  url: string;
  title: string;
  snippet: string | null;
  publishedAt: string;
  summary: string | null;
  sentiment: number | null;
  sentimentSource: "llm" | "author" | null;
  eventType: string | null;
  importance: number | null;
  llmProvider: string | null;
  llmModel: string | null;
  llmStatus: string;
  /** Later reports of the same event folded into this one (D-139). */
  duplicates: number;
  stocks: NewsStock[];
  meta: {
    pushes?: number;
    boos?: number;
    likes?: number;
    comments?: number;
    stance?: "bullish" | "bearish" | null;
    clause?: string | null;
  };
};

export type NewsQuery = {
  channel?: Channel;
  /** Only items linked to these stocks (any relation). */
  stockIds?: string[];
  minImportance?: number;
  /** Only items published after this instant. */
  since?: Date;
  limit?: number;
};

/** The instant `hours` ago (kept out of components, which must render purely). */
export function hoursAgo(hours: number): Date {
  return new Date(Date.now() - hours * 3_600_000);
}

/** Holdings (replayed by the portfolio engine) and the watchlist. */
export async function watchedStockIds(db: Kysely<DB>): Promise<string[]> {
  const [portfolio, watch] = await Promise.all([
    loadPortfolio(db),
    db.selectFrom("watchlist").select("stock_id").execute(),
  ]);
  const ids = new Set(watch.map((w) => String(w.stock_id)));
  for (const p of portfolio.ledger.positions) if (p.shares > 0) ids.add(p.stock);
  return [...ids];
}

/** Representative items (duplicates folded) newest first, with their linked stocks. */
export async function listNews(db: Kysely<DB>, query: NewsQuery = {}): Promise<NewsListItem[]> {
  const { channel, stockIds, minImportance, since, limit = 50 } = query;
  if (stockIds && stockIds.length === 0) return [];
  const result = await sql<NewsListItem & { publishedAt: Date }>`
    SELECT i.id::text AS id, i.channel, s.name AS source, i.url, i.title, i.snippet,
           i.published_at AS "publishedAt", i.summary, i.sentiment::float8 AS sentiment,
           i.sentiment_source AS "sentimentSource", i.event_type AS "eventType", i.importance,
           i.llm_provider AS "llmProvider", i.llm_model AS "llmModel", i.llm_status AS "llmStatus",
           i.meta,
           (SELECT count(*)::int FROM news_items d WHERE d.duplicate_of = i.id) AS duplicates,
           coalesce((
             SELECT json_agg(json_build_object(
                      'symbol', st.symbol, 'name', st.name, 'relation', l.relation,
                      'sentiment', l.sentiment::float8)
                    ORDER BY l.relation, st.symbol)
             FROM news_item_stocks l JOIN stocks st ON st.id = l.stock_id
             WHERE l.item_id = i.id), '[]'::json) AS stocks
    FROM news_items i
    JOIN news_sources s ON s.id = i.source_id
    WHERE i.duplicate_of IS NULL
      ${channel ? sql`AND i.channel = ${channel}` : sql``}
      ${minImportance ? sql`AND i.importance >= ${minImportance}` : sql``}
      ${since ? sql`AND i.published_at >= ${since}` : sql``}
      ${
        stockIds
          ? sql`AND EXISTS (SELECT 1 FROM news_item_stocks l WHERE l.item_id = i.id
                  AND l.stock_id = ANY(${stockIds}::bigint[]))`
          : sql``
      }
    ORDER BY i.published_at DESC, i.id DESC
    LIMIT ${limit}
  `.execute(db);
  return result.rows.map((r) => ({ ...r, publishedAt: r.publishedAt.toISOString() }));
}

export type SentimentPoint = {
  tradeDate: string;
  scope: string;
  items: number;
  sentiment: number | null;
  bullish: number;
  bearish: number;
};

/** Daily sentiment of one stock over the last `days` calendar days, oldest first. */
export async function stockSentiment(
  db: Kysely<DB>,
  stockId: string,
  days = 120,
): Promise<SentimentPoint[]> {
  const rows = await db
    .selectFrom("sentiment_daily")
    .select([
      sql<string>`trade_date::text`.as("tradeDate"),
      "scope",
      "items",
      sql<number | null>`sentiment::float8`.as("sentiment"),
      "bullish",
      "bearish",
    ])
    .where("stock_id", "=", stockId)
    .where(sql<boolean>`trade_date >= current_date - ${days}::int`)
    .orderBy("trade_date")
    .execute();
  return rows;
}

export type NewsCoverage = {
  items: number;
  pending: number;
  lastFetch: string | null;
  sourcesWithErrors: number;
  firstItem: string | null;
};

/** For the empty states and /status: how much is there and how fresh. */
export async function newsCoverage(db: Kysely<DB>): Promise<NewsCoverage> {
  const row = await sql<{
    items: number;
    pending: number;
    lastFetch: Date | null;
    errors: number;
    firstItem: Date | null;
  }>`
    SELECT (SELECT count(*)::int FROM news_items) AS items,
           (SELECT count(*)::int FROM news_items WHERE llm_status = 'pending') AS pending,
           (SELECT max(last_fetched_at) FROM news_sources) AS "lastFetch",
           (SELECT count(*)::int FROM news_sources WHERE enabled AND last_error IS NOT NULL) AS errors,
           (SELECT min(published_at) FROM news_items) AS "firstItem"
  `.execute(db);
  const r = row.rows[0];
  return {
    items: r.items,
    pending: r.pending,
    lastFetch: r.lastFetch?.toISOString() ?? null,
    sourcesWithErrors: r.errors,
    firstItem: r.firstItem?.toISOString() ?? null,
  };
}
