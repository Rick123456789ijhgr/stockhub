import "server-only";

import { type Kysely, sql, type Transaction } from "kysely";

import type { DB } from "@/lib/db";
import {
  type AliasInput,
  type LlmCreate,
  type LlmPatch,
  type NewsSettings,
  readNewsSettings,
  type SlangInput,
  type SourceCreate,
  type SourcePatch,
} from "@/lib/news-admin-input";
import type { Result } from "@/lib/themes";

const fail = (status: number, error: string): Result => ({ ok: false, status, error });
const done: Result = { ok: true };

async function audit(trx: Transaction<DB>, actor: string, action: string, target: string, detail: unknown) {
  await trx
    .insertInto("audit_log")
    .values({ actor, action, target, detail: JSON.stringify(detail) })
    .execute();
}

function isUniqueViolation(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { code?: unknown }).code === "23505";
}

// --- reads ----------------------------------------------------------------------------

export type SourceRow = {
  id: string;
  code: string;
  name: string;
  kind: string;
  channel: string;
  url: string | null;
  perStock: boolean;
  enabled: boolean;
  intervalMinutes: number;
  keywords: string[];
  useLlm: boolean;
  lastFetchedAt: string | null;
  lastSuccessAt: string | null;
  lastError: string | null;
  items7d: number;
};

export async function listSources(db: Kysely<DB>): Promise<SourceRow[]> {
  const result = await sql<
    Omit<SourceRow, "lastFetchedAt" | "lastSuccessAt"> & {
      lastFetchedAt: Date | null;
      lastSuccessAt: Date | null;
    }
  >`
    SELECT s.id::text AS id, s.code, s.name, s.kind, s.channel, s.url, s.per_stock AS "perStock",
           s.enabled, s.interval_minutes AS "intervalMinutes", s.keywords, s.use_llm AS "useLlm",
           s.last_fetched_at AS "lastFetchedAt", s.last_success_at AS "lastSuccessAt",
           s.last_error AS "lastError",
           (SELECT count(*)::int FROM news_items i WHERE i.source_id = s.id
              AND i.fetched_at >= now() - interval '7 days') AS "items7d"
    FROM news_sources s ORDER BY s.channel DESC, s.id
  `.execute(db);
  return result.rows.map((r) => ({
    ...r,
    lastFetchedAt: r.lastFetchedAt?.toISOString() ?? null,
    lastSuccessAt: r.lastSuccessAt?.toISOString() ?? null,
  }));
}

export type LlmRow = {
  id: string;
  code: string;
  name: string;
  baseUrl: string;
  model: string;
  apiKeyEnv: string;
  /** Whether the key's variable is set where the site runs (the value is never read out). */
  keySet: boolean;
  priority: number;
  enabled: boolean;
  paid: boolean;
  requestsPerMinute: number | null;
  requestsPerDay: number | null;
  jsonMode: string;
  cooldownUntil: string | null;
  /** Cooling down right now (not asked until cooldownUntil). */
  resting: boolean;
  lastError: string | null;
  lastErrorAt: string | null;
  lastSuccessAt: string | null;
  today: { requests: number; failures: number; tokens: number; costUsd: number };
  week: { requests: number; tokens: number; costUsd: number };
};

export async function listLlmProviders(db: Kysely<DB>, env = process.env): Promise<LlmRow[]> {
  const result = await sql<{
    id: string;
    code: string;
    name: string;
    baseUrl: string;
    model: string;
    apiKeyEnv: string;
    priority: number;
    enabled: boolean;
    paid: boolean;
    requestsPerMinute: number | null;
    requestsPerDay: number | null;
    jsonMode: string;
    cooldownUntil: Date | null;
    resting: boolean;
    lastError: string | null;
    lastErrorAt: Date | null;
    lastSuccessAt: Date | null;
    todayRequests: number;
    todayFailures: number;
    todayTokens: number;
    todayCost: number;
    weekRequests: number;
    weekTokens: number;
    weekCost: number;
  }>`
    SELECT p.id::text AS id, p.code, p.name, p.base_url AS "baseUrl", p.model,
           p.api_key_env AS "apiKeyEnv", p.priority, p.enabled, p.paid,
           p.requests_per_minute AS "requestsPerMinute", p.requests_per_day AS "requestsPerDay",
           p.json_mode AS "jsonMode", p.cooldown_until AS "cooldownUntil",
           coalesce(p.cooldown_until > now(), false) AS resting,
           p.last_error AS "lastError", p.last_error_at AS "lastErrorAt",
           p.last_success_at AS "lastSuccessAt",
           coalesce(t.requests, 0) AS "todayRequests", coalesce(t.failures, 0) AS "todayFailures",
           coalesce(t.input_tokens + t.output_tokens, 0)::int8 AS "todayTokens",
           coalesce(t.cost_usd, 0)::float8 AS "todayCost",
           coalesce(w.requests, 0)::int AS "weekRequests",
           coalesce(w.tokens, 0)::int8 AS "weekTokens", coalesce(w.cost, 0)::float8 AS "weekCost"
    FROM llm_providers p
    LEFT JOIN llm_usage t ON t.provider_id = p.id
      AND t.usage_date = (now() AT TIME ZONE 'Asia/Taipei')::date
    LEFT JOIN LATERAL (
      SELECT sum(requests) AS requests, sum(input_tokens + output_tokens) AS tokens,
             sum(cost_usd) AS cost
      FROM llm_usage WHERE provider_id = p.id
        AND usage_date > (now() AT TIME ZONE 'Asia/Taipei')::date - 7
    ) w ON true
    ORDER BY p.priority, p.id
  `.execute(db);
  return result.rows.map((r) => ({
    id: r.id,
    code: r.code,
    name: r.name,
    baseUrl: r.baseUrl,
    model: r.model,
    apiKeyEnv: r.apiKeyEnv,
    keySet: Boolean(env[r.apiKeyEnv]?.trim()),
    priority: r.priority,
    enabled: r.enabled,
    paid: r.paid,
    requestsPerMinute: r.requestsPerMinute,
    requestsPerDay: r.requestsPerDay,
    jsonMode: r.jsonMode,
    cooldownUntil: r.cooldownUntil?.toISOString() ?? null,
    resting: r.resting,
    lastError: r.lastError,
    lastErrorAt: r.lastErrorAt?.toISOString() ?? null,
    lastSuccessAt: r.lastSuccessAt?.toISOString() ?? null,
    today: {
      requests: r.todayRequests,
      failures: r.todayFailures,
      tokens: Number(r.todayTokens),
      costUsd: r.todayCost,
    },
    week: { requests: r.weekRequests, tokens: Number(r.weekTokens), costUsd: r.weekCost },
  }));
}

export type SlangRow = { id: string; term: string; meaning: string; polarity: number | null };

export async function listSlang(db: Kysely<DB>): Promise<SlangRow[]> {
  const rows = await db
    .selectFrom("slang_terms")
    .select(["id", "term", "meaning", "polarity"])
    .orderBy("term")
    .execute();
  return rows.map((r) => ({ ...r, id: String(r.id) }));
}

export type AliasRow = { alias: string; symbol: string; name: string };

export async function listAliases(db: Kysely<DB>): Promise<AliasRow[]> {
  return db
    .selectFrom("stock_aliases as a")
    .innerJoin("stocks as s", "s.id", "a.stock_id")
    .select(["a.alias", "s.symbol", "s.name"])
    .orderBy("s.symbol")
    .orderBy("a.alias")
    .execute();
}

export async function getNewsSettings(db: Kysely<DB>): Promise<NewsSettings> {
  const row = await db.selectFrom("settings").select("value").where("key", "=", "news").executeTakeFirst();
  return readNewsSettings(row?.value ?? null);
}

// --- writes ---------------------------------------------------------------------------

export async function createSource(db: Kysely<DB>, input: SourceCreate, actor: string): Promise<Result> {
  const code = `rss_${Date.now().toString(36)}`;
  return db.transaction().execute(async (trx) => {
    await trx
      .insertInto("news_sources")
      .values({
        code,
        name: input.name,
        kind: "rss",
        channel: "news",
        url: input.url,
        per_stock: input.perStock,
        interval_minutes: input.intervalMinutes,
        keywords: input.keywords,
        use_llm: input.useLlm,
      })
      .execute();
    await audit(trx, actor, "news_source.create", input.name, { code, ...input });
    return done;
  });
}

export async function updateSource(
  db: Kysely<DB>,
  id: string,
  patch: SourcePatch,
  actor: string,
): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const before = await trx
      .selectFrom("news_sources")
      .select(["name", "kind", "enabled", "interval_minutes", "keywords", "use_llm"])
      .where("id", "=", id)
      .forUpdate()
      .executeTakeFirst();
    if (!before) return fail(404, "找不到來源");
    if (patch.enabled === true && before.kind === "cmoney_notes") {
      return fail(409, "這個來源還沒有可用的抓取程式（D-143）");
    }
    await trx
      .updateTable("news_sources")
      .set({
        ...(patch.name !== undefined ? { name: patch.name } : {}),
        ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}),
        ...(patch.intervalMinutes !== undefined ? { interval_minutes: patch.intervalMinutes } : {}),
        ...(patch.keywords !== undefined ? { keywords: patch.keywords } : {}),
        ...(patch.useLlm !== undefined ? { use_llm: patch.useLlm } : {}),
      })
      .where("id", "=", id)
      .execute();
    await audit(trx, actor, "news_source.update", patch.name ?? before.name, { id, before, ...patch });
    return done;
  });
}

/** Only RSS feeds can be removed (with their items); the built-in adapters are disabled instead. */
export async function deleteSource(db: Kysely<DB>, id: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .selectFrom("news_sources")
      .select(["name", "kind", "code", "url"])
      .where("id", "=", id)
      .forUpdate()
      .executeTakeFirst();
    if (!row) return fail(404, "找不到來源");
    if (row.kind !== "rss") return fail(409, "內建的來源不能刪除，只能停用");
    await trx.deleteFrom("news_sources").where("id", "=", id).execute();
    await audit(trx, actor, "news_source.delete", row.name, { id, code: row.code, url: row.url });
    return done;
  });
}

export async function createLlmProvider(db: Kysely<DB>, input: LlmCreate, actor: string): Promise<Result> {
  try {
    return await db.transaction().execute(async (trx) => {
      await trx
        .insertInto("llm_providers")
        .values({
          code: input.code,
          name: input.name,
          base_url: input.baseUrl,
          model: input.model,
          api_key_env: input.apiKeyEnv,
          priority: input.priority,
          paid: input.paid,
          requests_per_minute: input.requestsPerMinute,
          requests_per_day: input.requestsPerDay,
          json_mode: input.jsonMode,
          input_usd_per_mtok: input.inputUsdPerMtok === null ? null : String(input.inputUsdPerMtok),
          output_usd_per_mtok: input.outputUsdPerMtok === null ? null : String(input.outputUsdPerMtok),
        })
        .execute();
      await audit(trx, actor, "llm_provider.create", input.name, input);
      return done;
    });
  } catch (error) {
    if (isUniqueViolation(error)) return fail(409, "已有相同代碼的服務");
    throw error;
  }
}

export async function updateLlmProvider(
  db: Kysely<DB>,
  id: string,
  patch: LlmPatch,
  actor: string,
): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const before = await trx
      .selectFrom("llm_providers")
      .select(["name", "enabled", "priority", "model", "requests_per_minute", "requests_per_day", "json_mode"])
      .where("id", "=", id)
      .forUpdate()
      .executeTakeFirst();
    if (!before) return fail(404, "找不到服務");
    await trx
      .updateTable("llm_providers")
      .set({
        ...(patch.enabled !== undefined ? { enabled: patch.enabled } : {}),
        ...(patch.priority !== undefined ? { priority: patch.priority } : {}),
        ...(patch.model !== undefined ? { model: patch.model } : {}),
        ...(patch.requestsPerMinute !== undefined ? { requests_per_minute: patch.requestsPerMinute } : {}),
        ...(patch.requestsPerDay !== undefined ? { requests_per_day: patch.requestsPerDay } : {}),
        ...(patch.jsonMode !== undefined ? { json_mode: patch.jsonMode } : {}),
        ...(patch.clearCooldown ? { cooldown_until: null, last_error: null } : {}),
      })
      .where("id", "=", id)
      .execute();
    await audit(trx, actor, "llm_provider.update", before.name, { id, before, ...patch });
    return done;
  });
}

export async function deleteLlmProvider(db: Kysely<DB>, id: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .selectFrom("llm_providers")
      .select(["name", "code"])
      .where("id", "=", id)
      .forUpdate()
      .executeTakeFirst();
    if (!row) return fail(404, "找不到服務");
    await trx.deleteFrom("llm_providers").where("id", "=", id).execute();
    await audit(trx, actor, "llm_provider.delete", row.name, { id, code: row.code });
    return done;
  });
}

export async function createSlang(db: Kysely<DB>, input: SlangInput, actor: string): Promise<Result> {
  try {
    return await db.transaction().execute(async (trx) => {
      await trx.insertInto("slang_terms").values(input).execute();
      await audit(trx, actor, "slang.create", input.term, input);
      return done;
    });
  } catch (error) {
    if (isUniqueViolation(error)) return fail(409, "詞典已有這個詞");
    throw error;
  }
}

export async function updateSlang(
  db: Kysely<DB>,
  id: string,
  input: SlangInput,
  actor: string,
): Promise<Result> {
  try {
    return await db.transaction().execute(async (trx) => {
      const before = await trx
        .selectFrom("slang_terms")
        .select(["term", "meaning", "polarity"])
        .where("id", "=", id)
        .forUpdate()
        .executeTakeFirst();
      if (!before) return fail(404, "找不到詞條");
      await trx.updateTable("slang_terms").set(input).where("id", "=", id).execute();
      await audit(trx, actor, "slang.update", input.term, { id, before, ...input });
      return done;
    });
  } catch (error) {
    if (isUniqueViolation(error)) return fail(409, "詞典已有這個詞");
    throw error;
  }
}

export async function deleteSlang(db: Kysely<DB>, id: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .deleteFrom("slang_terms")
      .where("id", "=", id)
      .returning(["term", "meaning"])
      .executeTakeFirst();
    if (!row) return fail(404, "找不到詞條");
    await audit(trx, actor, "slang.delete", row.term, { id, meaning: row.meaning });
    return done;
  });
}

export async function createAlias(db: Kysely<DB>, input: AliasInput, actor: string): Promise<Result> {
  try {
    return await db.transaction().execute(async (trx) => {
      const stock = await trx
        .selectFrom("stocks")
        .select(["id", "name"])
        .where("symbol", "=", input.symbol)
        .where("delisted_date", "is", null)
        .executeTakeFirst();
      if (!stock) return fail(404, `找不到股票 ${input.symbol}`);
      await trx.insertInto("stock_aliases").values({ alias: input.alias, stock_id: stock.id }).execute();
      await audit(trx, actor, "alias.create", input.alias, { ...input, name: stock.name });
      return done;
    });
  } catch (error) {
    if (isUniqueViolation(error)) return fail(409, "這個別名已經用在其他股票");
    throw error;
  }
}

export async function deleteAlias(db: Kysely<DB>, alias: string, actor: string): Promise<Result> {
  return db.transaction().execute(async (trx) => {
    const row = await trx
      .deleteFrom("stock_aliases")
      .where("alias", "=", alias)
      .returning("stock_id")
      .executeTakeFirst();
    if (!row) return fail(404, "找不到別名");
    await audit(trx, actor, "alias.delete", alias, { stockId: String(row.stock_id) });
    return done;
  });
}

/** Replace the news settings (no-op when nothing changed); audited. */
export async function saveNewsSettings(db: Kysely<DB>, input: NewsSettings, actor: string): Promise<void> {
  await db.transaction().execute(async (trx) => {
    const row = await trx.selectFrom("settings").select("value").where("key", "=", "news").executeTakeFirst();
    const before = readNewsSettings(row?.value ?? null);
    if (JSON.stringify(before) === JSON.stringify(input) && row) return;
    await trx
      .insertInto("settings")
      .values({ key: "news", value: JSON.stringify(input) })
      .onConflict((oc) => oc.column("key").doUpdateSet({ value: JSON.stringify(input) }))
      .execute();
    await audit(trx, actor, "settings.news", "news", { before, after: input });
  });
}
