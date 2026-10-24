import { describe, expect, it } from "vitest";

import {
  NEWS_SETTINGS_DEFAULT,
  parseAliasInput,
  parseKeywords,
  parseLlmCreate,
  parseLlmPatch,
  parseNewsSettings,
  parseSlangInput,
  parseSourceCreate,
  parseSourcePatch,
  readNewsSettings,
} from "./news-admin-input";

describe("sources", () => {
  it("accepts an RSS feed and detects per-stock templates", () => {
    expect(parseSourceCreate({ name: " 我的財經 ", url: "https://a.example/rss" })).toEqual({
      name: "我的財經",
      url: "https://a.example/rss",
      perStock: false,
      intervalMinutes: 15,
      keywords: [],
      useLlm: true,
    });
    const perStock = parseSourceCreate({
      name: "個股",
      url: "https://a.example/rss?s={symbol}.{market_suffix}",
      intervalMinutes: "30",
      keywords: "台積電, 法說 法說",
      useLlm: false,
    });
    expect(perStock).toMatchObject({ perStock: true, intervalMinutes: 30, keywords: ["台積電", "法說"], useLlm: false });
  });

  it("rejects bad URLs, intervals and keywords", () => {
    expect(parseSourceCreate({ name: "x", url: "ftp://a.example/rss" })).toBeNull();
    expect(parseSourceCreate({ name: "x", url: "not a url" })).toBeNull();
    expect(parseSourceCreate({ name: "x", url: "https://a.example", intervalMinutes: 1 })).toBeNull();
    expect(parseSourceCreate({ name: "", url: "https://a.example" })).toBeNull();
    expect(parseKeywords(Array.from({ length: 11 }, (_, i) => `k${i}`))).toBeNull();
    expect(parseKeywords("x".repeat(21))).toBeNull();
    expect(parseKeywords(42)).toBeNull();
  });

  it("patches only what is sent", () => {
    expect(parseSourcePatch({ enabled: false })).toEqual({ enabled: false });
    expect(parseSourcePatch({ intervalMinutes: 60, keywords: [] })).toEqual({ intervalMinutes: 60, keywords: [] });
    expect(parseSourcePatch({ enabled: "no" })).toBeNull();
    expect(parseSourcePatch({})).toBeNull();
  });
});

describe("LLM services", () => {
  const base = {
    code: "mistral",
    name: "Mistral",
    baseUrl: "https://api.mistral.ai/v1/",
    model: "mistral-small-latest",
    apiKeyEnv: "MISTRAL_API_KEY",
    priority: 50,
  };

  it("accepts an OpenAI-compatible service", () => {
    expect(parseLlmCreate(base)).toEqual({
      ...base,
      baseUrl: "https://api.mistral.ai/v1",
      paid: false,
      requestsPerMinute: null,
      requestsPerDay: null,
      jsonMode: "json_object",
      inputUsdPerMtok: null,
      outputUsdPerMtok: null,
    });
    expect(parseLlmCreate({ ...base, requestsPerMinute: "20", requestsPerDay: "" })).toMatchObject({
      requestsPerMinute: 20,
      requestsPerDay: null,
    });
  });

  it("rejects unsafe or incomplete services", () => {
    expect(parseLlmCreate({ ...base, baseUrl: "http://api.example/v1" })).toBeNull();
    expect(parseLlmCreate({ ...base, apiKeyEnv: "lower_case" })).toBeNull();
    expect(parseLlmCreate({ ...base, code: "Bad Code" })).toBeNull();
    expect(parseLlmCreate({ ...base, paid: true })).toBeNull();
    expect(parseLlmCreate({ ...base, paid: true, inputUsdPerMtok: 0.1, outputUsdPerMtok: 0.4 })).toMatchObject({
      paid: true,
      inputUsdPerMtok: 0.1,
    });
    expect(parseLlmCreate({ ...base, jsonMode: "xml" })).toBeNull();
  });

  it("patches priority, limits, model and cooldown", () => {
    expect(parseLlmPatch({ priority: 5, requestsPerDay: null, clearCooldown: true })).toEqual({
      priority: 5,
      requestsPerDay: null,
      clearCooldown: true,
    });
    expect(parseLlmPatch({ priority: 0 })).toBeNull();
    expect(parseLlmPatch({ model: "" })).toBeNull();
    expect(parseLlmPatch({})).toBeNull();
  });
});

describe("dictionary and aliases", () => {
  it("validates slang terms", () => {
    expect(parseSlangInput({ term: "丸子", meaning: "完了", polarity: -1 })).toEqual({
      term: "丸子",
      meaning: "完了",
      polarity: -1,
    });
    expect(parseSlangInput({ term: "上車", meaning: "買進", polarity: "" })).toMatchObject({ polarity: null });
    expect(parseSlangInput({ term: "x", meaning: "y", polarity: 2 })).toBeNull();
    expect(parseSlangInput({ term: "", meaning: "y" })).toBeNull();
  });

  it("validates aliases", () => {
    expect(parseAliasInput({ alias: "神山", symbol: "2330" })).toEqual({ alias: "神山", symbol: "2330" });
    expect(parseAliasInput({ alias: "台", symbol: "2330" })).toBeNull();
    expect(parseAliasInput({ alias: "台積", symbol: "TSMC!" })).toBeNull();
  });
});

describe("news settings", () => {
  it("parses within ranges and fills defaults when reading", () => {
    expect(parseNewsSettings(NEWS_SETTINGS_DEFAULT)).toEqual(NEWS_SETTINGS_DEFAULT);
    expect(parseNewsSettings({ ...NEWS_SETTINGS_DEFAULT, sentimentAlert: 0.1 })).toBeNull();
    expect(parseNewsSettings({ ...NEWS_SETTINGS_DEFAULT, importanceAlert: 4.5 })).toBeNull();
    expect(readNewsSettings({ sentimentAlert: 0.6, llmDailyItems: "x" })).toEqual({
      ...NEWS_SETTINGS_DEFAULT,
      sentimentAlert: 0.6,
    });
    expect(readNewsSettings(null)).toEqual(NEWS_SETTINGS_DEFAULT);
  });
});
