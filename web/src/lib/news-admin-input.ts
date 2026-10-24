/**
 * Validation of the /admin news requests (pure): RSS sources, LLM services, the slang
 * dictionary, stock aliases and the news settings. The tables' CHECKs guard the rest.
 */

const body = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

const text = (value: unknown, max: number, min = 1): string | null => {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length >= min && trimmed.length <= max ? trimmed : null;
};

const int = (value: unknown, min: number, max: number): number | null => {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isInteger(n) && n >= min && n <= max ? n : null;
};

const num = (value: unknown, min: number, max: number): number | null => {
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) && n >= min && n <= max ? n : null;
};

/** Optional nullable integer: null = absent or cleared, undefined = invalid. */
const optionalInt = (value: unknown, min: number, max: number): number | null | undefined => {
  if (value === undefined || value === null || value === "") return null;
  return int(value, min, max) ?? undefined;
};

function httpUrl(value: unknown, https = false): string | null {
  const raw = text(value, 500);
  if (!raw) return null;
  try {
    // Placeholders are not valid in a hostname check; test with a sample stock.
    const url = new URL(raw.replaceAll("{symbol}", "2330").replaceAll("{market_suffix}", "TW"));
    if (url.protocol !== "https:" && (https || url.protocol !== "http:")) return null;
    return raw;
  } catch {
    return null;
  }
}

/** Up to 10 words of at most 20 characters, from an array or a comma/space separated text. */
export function parseKeywords(value: unknown): string[] | null {
  const words =
    typeof value === "string"
      ? value.split(/[,，\s]+/)
      : Array.isArray(value)
        ? value.map((v) => (typeof v === "string" ? v : ""))
        : value === undefined || value === null
          ? []
          : null;
  if (words === null) return null;
  const out = [...new Set(words.map((w) => w.trim()).filter(Boolean))];
  return out.length <= 10 && out.every((w) => w.length <= 20) ? out : null;
}

export type SourceCreate = {
  name: string;
  url: string;
  perStock: boolean;
  intervalMinutes: number;
  keywords: string[];
  useLlm: boolean;
};

/** A new RSS feed. A URL with {symbol} is fetched once per held or watched stock. */
export function parseSourceCreate(value: unknown): SourceCreate | null {
  const raw = body(value);
  const name = text(raw.name, 40);
  const url = httpUrl(raw.url);
  const intervalMinutes = raw.intervalMinutes === undefined ? 15 : int(raw.intervalMinutes, 5, 1440);
  const keywords = parseKeywords(raw.keywords);
  if (!name || !url || intervalMinutes === null || keywords === null) return null;
  return {
    name,
    url,
    perStock: url.includes("{symbol}"),
    intervalMinutes,
    keywords,
    useLlm: raw.useLlm !== false,
  };
}

export type SourcePatch = Partial<{
  name: string;
  enabled: boolean;
  intervalMinutes: number;
  keywords: string[];
  useLlm: boolean;
}>;

export function parseSourcePatch(value: unknown): SourcePatch | null {
  const raw = body(value);
  const out: SourcePatch = {};
  if (raw.name !== undefined) {
    const name = text(raw.name, 40);
    if (!name) return null;
    out.name = name;
  }
  if (raw.enabled !== undefined) {
    if (typeof raw.enabled !== "boolean") return null;
    out.enabled = raw.enabled;
  }
  if (raw.intervalMinutes !== undefined) {
    const minutes = int(raw.intervalMinutes, 1, 1440);
    if (minutes === null) return null;
    out.intervalMinutes = minutes;
  }
  if (raw.keywords !== undefined) {
    const keywords = parseKeywords(raw.keywords);
    if (keywords === null) return null;
    out.keywords = keywords;
  }
  if (raw.useLlm !== undefined) {
    if (typeof raw.useLlm !== "boolean") return null;
    out.useLlm = raw.useLlm;
  }
  return Object.keys(out).length > 0 ? out : null;
}

export const JSON_MODES = ["json_object", "json_schema", "none"] as const;
export type JsonMode = (typeof JSON_MODES)[number];

export type LlmCreate = {
  code: string;
  name: string;
  baseUrl: string;
  model: string;
  apiKeyEnv: string;
  priority: number;
  paid: boolean;
  requestsPerMinute: number | null;
  requestsPerDay: number | null;
  jsonMode: JsonMode;
  inputUsdPerMtok: number | null;
  outputUsdPerMtok: number | null;
};

const CODE = /^[a-z0-9_]{2,30}$/;
const ENV = /^[A-Z][A-Z0-9_]{1,60}$/;

/** A new OpenAI-compatible service (D-137); paid ones need both prices. */
export function parseLlmCreate(value: unknown): LlmCreate | null {
  const raw = body(value);
  const code = typeof raw.code === "string" ? raw.code.trim() : "";
  const name = text(raw.name, 40);
  const baseUrl = httpUrl(raw.baseUrl, true);
  const model = text(raw.model, 100);
  const apiKeyEnv = typeof raw.apiKeyEnv === "string" ? raw.apiKeyEnv.trim() : "";
  const priority = int(raw.priority, 1, 999);
  const rpm = optionalInt(raw.requestsPerMinute, 1, 10_000);
  const rpd = optionalInt(raw.requestsPerDay, 1, 1_000_000);
  const jsonMode = (raw.jsonMode ?? "json_object") as JsonMode;
  const paid = raw.paid === true;
  const priceIn = raw.inputUsdPerMtok === undefined || raw.inputUsdPerMtok === "" ? null : num(raw.inputUsdPerMtok, 0, 1000);
  const priceOut = raw.outputUsdPerMtok === undefined || raw.outputUsdPerMtok === "" ? null : num(raw.outputUsdPerMtok, 0, 1000);
  if (
    !CODE.test(code) ||
    !name ||
    !baseUrl ||
    !model ||
    !ENV.test(apiKeyEnv) ||
    priority === null ||
    rpm === undefined ||
    rpd === undefined ||
    !JSON_MODES.includes(jsonMode) ||
    (paid && (priceIn === null || priceOut === null))
  ) {
    return null;
  }
  return {
    code,
    name,
    baseUrl: baseUrl.replace(/\/+$/, ""),
    model,
    apiKeyEnv,
    priority,
    paid,
    requestsPerMinute: rpm,
    requestsPerDay: rpd,
    jsonMode,
    inputUsdPerMtok: priceIn,
    outputUsdPerMtok: priceOut,
  };
}

export type LlmPatch = Partial<{
  enabled: boolean;
  priority: number;
  model: string;
  requestsPerMinute: number | null;
  requestsPerDay: number | null;
  jsonMode: JsonMode;
  clearCooldown: true;
}>;

export function parseLlmPatch(value: unknown): LlmPatch | null {
  const raw = body(value);
  const out: LlmPatch = {};
  if (raw.enabled !== undefined) {
    if (typeof raw.enabled !== "boolean") return null;
    out.enabled = raw.enabled;
  }
  if (raw.priority !== undefined) {
    const priority = int(raw.priority, 1, 999);
    if (priority === null) return null;
    out.priority = priority;
  }
  if (raw.model !== undefined) {
    const model = text(raw.model, 100);
    if (!model) return null;
    out.model = model;
  }
  if (raw.requestsPerMinute !== undefined) {
    const rpm = optionalInt(raw.requestsPerMinute, 1, 10_000);
    if (rpm === undefined) return null;
    out.requestsPerMinute = rpm;
  }
  if (raw.requestsPerDay !== undefined) {
    const rpd = optionalInt(raw.requestsPerDay, 1, 1_000_000);
    if (rpd === undefined) return null;
    out.requestsPerDay = rpd;
  }
  if (raw.jsonMode !== undefined) {
    if (!JSON_MODES.includes(raw.jsonMode as JsonMode)) return null;
    out.jsonMode = raw.jsonMode as JsonMode;
  }
  if (raw.clearCooldown === true) out.clearCooldown = true;
  return Object.keys(out).length > 0 ? out : null;
}

export type SlangInput = { term: string; meaning: string; polarity: -1 | 0 | 1 | null };

export function parseSlangInput(value: unknown): SlangInput | null {
  const raw = body(value);
  const term = text(raw.term, 10);
  const meaning = text(raw.meaning, 100);
  const polarity = raw.polarity === null || raw.polarity === undefined || raw.polarity === "" ? null : int(raw.polarity, -1, 1);
  if (!term || !meaning || (polarity === null && raw.polarity !== null && raw.polarity !== undefined && raw.polarity !== "")) {
    return null;
  }
  return { term, meaning, polarity: polarity as -1 | 0 | 1 | null };
}

export type AliasInput = { alias: string; symbol: string };

export function parseAliasInput(value: unknown): AliasInput | null {
  const raw = body(value);
  const alias = text(raw.alias, 20, 2);
  const symbol = typeof raw.symbol === "string" ? raw.symbol.trim().toUpperCase() : "";
  if (!alias || !/^[0-9A-Z]{4,6}$/.test(symbol)) return null;
  return { alias, symbol };
}

export type NewsSettings = {
  llmDailyItems: number;
  llmDailyUsdCap: number;
  sentimentAlert: number;
  importanceAlert: number;
  buzzSigma: number;
  buzzMinPosts: number;
};

/** Mirrors NewsSettings in py/stockhub/etl/jobs/news.py. */
export const NEWS_SETTINGS_DEFAULT: NewsSettings = {
  llmDailyItems: 400,
  llmDailyUsdCap: 0,
  sentimentAlert: 0.7,
  importanceAlert: 4,
  buzzSigma: 3,
  buzzMinPosts: 5,
};

export function parseNewsSettings(value: unknown): NewsSettings | null {
  const raw = body(value);
  const parsed = {
    llmDailyItems: int(raw.llmDailyItems, 0, 5000),
    llmDailyUsdCap: num(raw.llmDailyUsdCap, 0, 100),
    sentimentAlert: num(raw.sentimentAlert, 0.3, 1),
    importanceAlert: int(raw.importanceAlert, 1, 5),
    buzzSigma: num(raw.buzzSigma, 1, 10),
    buzzMinPosts: int(raw.buzzMinPosts, 1, 100),
  };
  return Object.values(parsed).every((v) => v !== null) ? (parsed as NewsSettings) : null;
}

/** Stored settings over the defaults (missing or unusable values fall back). */
export function readNewsSettings(stored: unknown): NewsSettings {
  const raw = body(stored);
  const merged = { ...NEWS_SETTINGS_DEFAULT };
  for (const key of Object.keys(NEWS_SETTINGS_DEFAULT) as (keyof NewsSettings)[]) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) merged[key] = value;
  }
  return merged;
}
