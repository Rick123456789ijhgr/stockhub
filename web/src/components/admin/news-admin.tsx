"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { JobButton } from "@/components/jobs/job-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatTaipeiDateTime } from "@/lib/format";
import type { AliasRow, LlmRow, SlangRow, SourceRow } from "@/lib/news-admin";
import type { NewsSettings } from "@/lib/news-admin-input";
import { sendJson } from "@/lib/send-json";
import { cn } from "@/lib/utils";

const field =
  "h-8 rounded-md border bg-background px-2 text-sm text-foreground aria-invalid:border-destructive";

function useSend() {
  const router = useRouter();
  return useMutation({
    mutationFn: ({ method, url, body }: { method: string; url: string; body?: unknown }) =>
      sendJson(method, url, body),
    onSuccess: () => router.refresh(),
  });
}

function ErrorText({ error }: { error: Error | null }) {
  return error ? <span className="text-xs text-destructive">{error.message}</span> : null;
}

const KIND_LABEL: Record<string, string> = {
  rss: "RSS",
  mops: "官方 OpenAPI",
  cnyes: "鉅亨網",
  cmoney_notes: "CMoney 網誌",
  ptt: "PTT",
  cmoney_forum: "同學會",
};
const INTERVALS = [5, 10, 15, 30, 60, 120, 240, 1440];

// --- sources --------------------------------------------------------------------------

/** News sources: turn on or off, timing, keyword filter, AI analysis; RSS feeds can be added. */
export function NewsSourcesEditor({ sources }: { sources: SourceRow[] }) {
  const create = useSend();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [keywords, setKeywords] = useState("");
  return (
    <div className="space-y-4">
      <ul className="divide-y">
        {sources.map((s) => (
          <SourceItem key={s.id} source={s} />
        ))}
      </ul>
      <form
        className="space-y-2 rounded-lg border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { method: "POST", url: "/api/admin/news-sources", body: { name, url, keywords } },
            {
              onSuccess: () => {
                setName("");
                setUrl("");
                setKeywords("");
              },
            },
          );
        }}
      >
        <p className="text-sm font-medium">新增 RSS 來源</p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className={`${field} w-36`}
            placeholder="名稱"
            aria-label="來源名稱"
            maxLength={40}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <input
            className={`${field} min-w-0 flex-1 basis-64`}
            placeholder="https://…/rss（可用 {symbol}、{market_suffix} 逐檔抓）"
            aria-label="RSS 網址"
            maxLength={500}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <input
            className={`${field} w-48`}
            placeholder="關鍵字（選填，空白分隔）"
            aria-label="關鍵字"
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
          />
          <Button type="submit" size="sm" disabled={!name.trim() || !url.trim() || create.isPending}>
            新增
          </Button>
          <ErrorText error={create.error} />
        </div>
        <p className="text-xs text-muted-foreground">
          每 15 分鐘抓一次；抓取前會先查該網站的 robots.txt，不允許的來源不會被抓，錯誤會顯示在這裡。網址含
          {" {symbol}"} 時，對每檔持股與自選股各抓一次（{"{market_suffix}"} 是 TW 或 TWO）。沒有 RSS 的網站需要另寫程式。
        </p>
      </form>
    </div>
  );
}

function SourceItem({ source }: { source: SourceRow }) {
  const action = useSend();
  const [keywords, setKeywords] = useState(source.keywords.join(" "));
  const base = `/api/admin/news-sources/${source.id}`;
  const patch = (body: Record<string, unknown>) => action.mutate({ method: "PATCH", url: base, body });
  return (
    <li className={cn("space-y-1.5 py-2.5 text-sm", !source.enabled && "text-muted-foreground")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{source.name}</span>
        <Badge variant="outline">{KIND_LABEL[source.kind] ?? source.kind}</Badge>
        {source.perStock ? <Badge variant="secondary">逐檔</Badge> : null}
        {!source.enabled ? <Badge variant="secondary">已停用</Badge> : null}
        <span className="text-xs text-muted-foreground">
          近 7 天 {source.items7d} 則，最後抓取 {formatTaipeiDateTime(source.lastFetchedAt)}
        </span>
      </div>
      {source.lastError ? (
        <p className="line-clamp-2 text-xs text-destructive" title={source.lastError}>
          最近一次失敗：{source.lastError}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="xs" variant="outline" disabled={action.isPending} onClick={() => patch({ enabled: !source.enabled })}>
          {source.enabled ? "停用" : "啟用"}
        </Button>
        <Button size="xs" variant="outline" disabled={action.isPending} onClick={() => patch({ useLlm: !source.useLlm })}>
          AI 分析：{source.useLlm ? "開" : "關"}
        </Button>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          間隔
          <select
            className={`${field} h-7`}
            value={source.intervalMinutes}
            onChange={(e) => patch({ intervalMinutes: Number(e.target.value) })}
          >
            {[...new Set([...INTERVALS, source.intervalMinutes])].sort((a, b) => a - b).map((m) => (
              <option key={m} value={m}>
                {m >= 60 ? `${m / 60} 小時` : `${m} 分鐘`}
              </option>
            ))}
          </select>
        </label>
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            patch({ keywords });
          }}
        >
          <input
            className={`${field} h-7 w-40`}
            placeholder="關鍵字過濾"
            aria-label="關鍵字過濾"
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
          />
          {keywords !== source.keywords.join(" ") ? (
            <Button type="submit" size="xs">
              儲存
            </Button>
          ) : null}
        </form>
        {source.enabled ? (
          <JobButton
            size="xs"
            variant="ghost"
            label="立即抓取"
            requests={[{ job: "sync_news", params: { force: "true", sources: source.code } }]}
          />
        ) : null}
        {source.kind === "rss" ? (
          <Button
            size="xs"
            variant="ghost"
            className="text-destructive"
            disabled={action.isPending}
            onClick={() => {
              if (window.confirm(`刪除「${source.name}」與它抓到的項目？`)) {
                action.mutate({ method: "DELETE", url: base });
              }
            }}
          >
            刪除
          </Button>
        ) : null}
        <ErrorText error={action.error} />
      </div>
    </li>
  );
}

// --- LLM services ---------------------------------------------------------------------

/** LLM services in priority order: key status, usage, cooldown; free ones first (D-137). */
export function LlmProvidersEditor({ providers }: { providers: LlmRow[] }) {
  return (
    <div className="space-y-4">
      <ul className="divide-y">
        {providers.map((p) => (
          <LlmItem key={p.id} provider={p} />
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <JobButton label="檢查所有服務" requests={[{ job: "check_llm_providers" }]} />
        <span className="text-xs text-muted-foreground">確認金鑰可用、模型名稱存在（各家的 /models 清單）。</span>
      </div>
      <NewLlmForm />
    </div>
  );
}

function LlmItem({ provider: p }: { provider: LlmRow }) {
  const action = useSend();
  const [model, setModel] = useState(p.model);
  const [priority, setPriority] = useState(String(p.priority));
  const [rpd, setRpd] = useState(p.requestsPerDay === null ? "" : String(p.requestsPerDay));
  const base = `/api/admin/llm-providers/${p.id}`;
  const patch = (body: Record<string, unknown>) => action.mutate({ method: "PATCH", url: base, body });
  const changed =
    model !== p.model || priority !== String(p.priority) || rpd !== (p.requestsPerDay === null ? "" : String(p.requestsPerDay));
  const resting = p.resting;
  return (
    <li className={cn("space-y-1.5 py-2.5 text-sm", !p.enabled && "text-muted-foreground")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{p.name}</span>
        {p.paid ? <Badge variant="outline">付費</Badge> : <Badge variant="secondary">免費</Badge>}
        <Badge variant={p.keySet ? "secondary" : "outline"} className={cn(!p.keySet && "text-destructive")}>
          {p.keySet ? "金鑰已設定" : `未設定 ${p.apiKeyEnv}`}
        </Badge>
        {!p.enabled ? <Badge variant="secondary">已停用</Badge> : null}
        {resting ? <Badge variant="outline">冷卻到 {formatTaipeiDateTime(p.cooldownUntil)}</Badge> : null}
        <span className="text-xs text-muted-foreground tabular-nums">
          今日 {p.today.requests} 次（失敗 {p.today.failures}）、{p.today.tokens.toLocaleString("zh-TW")} tokens；
          近 7 日 {p.week.requests} 次{p.paid ? `、US$${p.week.costUsd.toFixed(4)}` : ""}
        </span>
      </div>
      {p.lastError ? (
        <p className="line-clamp-2 text-xs text-destructive" title={p.lastError}>
          {formatTaipeiDateTime(p.lastErrorAt)}：{p.lastError}
        </p>
      ) : null}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          patch({ model, priority, requestsPerDay: rpd });
        }}
      >
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          順序
          <input className={`${field} h-7 w-14`} inputMode="numeric" value={priority} onChange={(e) => setPriority(e.target.value)} />
        </label>
        <label className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
          模型
          <input className={`${field} h-7 w-64 min-w-0`} value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          每日上限
          <input
            className={`${field} h-7 w-20`}
            inputMode="numeric"
            placeholder="不限"
            value={rpd}
            onChange={(e) => setRpd(e.target.value)}
          />
        </label>
        {changed ? (
          <Button type="submit" size="xs" disabled={action.isPending}>
            儲存
          </Button>
        ) : null}
        <Button type="button" size="xs" variant="outline" disabled={action.isPending} onClick={() => patch({ enabled: !p.enabled })}>
          {p.enabled ? "停用" : "啟用"}
        </Button>
        {resting || p.lastError ? (
          <Button type="button" size="xs" variant="ghost" disabled={action.isPending} onClick={() => patch({ clearCooldown: true })}>
            解除冷卻
          </Button>
        ) : null}
        <Button
          type="button"
          size="xs"
          variant="ghost"
          className="text-destructive"
          disabled={action.isPending}
          onClick={() => {
            if (window.confirm(`刪除「${p.name}」？`)) action.mutate({ method: "DELETE", url: base });
          }}
        >
          刪除
        </Button>
        <ErrorText error={action.error} />
      </form>
      <p className="truncate text-xs text-muted-foreground" title={p.baseUrl}>
        {p.baseUrl}
      </p>
    </li>
  );
}

function NewLlmForm() {
  const create = useSend();
  const empty = { code: "", name: "", baseUrl: "", model: "", apiKeyEnv: "", priority: "50", requestsPerMinute: "", requestsPerDay: "" };
  const [form, setForm] = useState(empty);
  const set = (key: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });
  return (
    <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer font-medium">新增服務</summary>
      <form
        className="mt-3 space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { method: "POST", url: "/api/admin/llm-providers", body: form },
            { onSuccess: () => setForm(empty) },
          );
        }}
      >
        <div className="flex flex-wrap gap-2">
          <input className={`${field} w-32`} placeholder="代碼（mistral）" aria-label="代碼" value={form.code} onChange={set("code")} />
          <input className={`${field} w-32`} placeholder="名稱" aria-label="名稱" value={form.name} onChange={set("name")} />
          <input
            className={`${field} min-w-0 flex-1 basis-64`}
            placeholder="https://…/v1（OpenAI 相容端點）"
            aria-label="端點"
            value={form.baseUrl}
            onChange={set("baseUrl")}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <input className={`${field} min-w-0 flex-1 basis-48`} placeholder="模型" aria-label="模型" value={form.model} onChange={set("model")} />
          <input className={`${field} w-48`} placeholder="金鑰變數（MISTRAL_API_KEY）" aria-label="金鑰變數" value={form.apiKeyEnv} onChange={set("apiKeyEnv")} />
          <input className={`${field} w-20`} placeholder="順序" aria-label="順序" inputMode="numeric" value={form.priority} onChange={set("priority")} />
          <input className={`${field} w-24`} placeholder="每分鐘" aria-label="每分鐘上限" inputMode="numeric" value={form.requestsPerMinute} onChange={set("requestsPerMinute")} />
          <input className={`${field} w-24`} placeholder="每日" aria-label="每日上限" inputMode="numeric" value={form.requestsPerDay} onChange={set("requestsPerDay")} />
          <Button type="submit" size="sm" disabled={create.isPending}>
            新增
          </Button>
          <ErrorText error={create.error} />
        </div>
        <p className="text-xs text-muted-foreground">
          金鑰不存在資料庫：在專案根目錄的 .env 加上「金鑰變數=金鑰」，排程下一輪就會用到（網站要重新啟動才會顯示「已設定」）。
          只會送出公開的新聞與貼文，不會送持股資料。
        </p>
      </form>
    </details>
  );
}

// --- dictionary and aliases -----------------------------------------------------------

const POLARITY: Record<string, string> = { "": "看情境", "1": "偏多", "0": "中性", "-1": "偏空" };

/** The slang dictionary sent with forum posts to the LLM. */
export function SlangEditor({ terms }: { terms: SlangRow[] }) {
  const create = useSend();
  const [term, setTerm] = useState("");
  const [meaning, setMeaning] = useState("");
  const [polarity, setPolarity] = useState("");
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { method: "POST", url: "/api/admin/slang", body: { term, meaning, polarity } },
            {
              onSuccess: () => {
                setTerm("");
                setMeaning("");
                setPolarity("");
              },
            },
          );
        }}
      >
        <input className={`${field} w-24`} placeholder="用語" aria-label="用語" maxLength={10} value={term} onChange={(e) => setTerm(e.target.value)} />
        <input
          className={`${field} min-w-0 flex-1 basis-48`}
          placeholder="意思"
          aria-label="意思"
          maxLength={100}
          value={meaning}
          onChange={(e) => setMeaning(e.target.value)}
        />
        <select className={field} aria-label="方向" value={polarity} onChange={(e) => setPolarity(e.target.value)}>
          {Object.entries(POLARITY).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        <Button type="submit" size="sm" disabled={!term.trim() || !meaning.trim() || create.isPending}>
          新增
        </Button>
        <ErrorText error={create.error} />
      </form>
      <ul className="divide-y text-sm">
        {terms.map((t) => (
          <SlangItem key={t.id} term={t} />
        ))}
      </ul>
    </div>
  );
}

function SlangItem({ term: t }: { term: SlangRow }) {
  const action = useSend();
  const [meaning, setMeaning] = useState(t.meaning);
  const [polarity, setPolarity] = useState(t.polarity === null ? "" : String(t.polarity));
  const base = `/api/admin/slang/${t.id}`;
  const changed = meaning !== t.meaning || polarity !== (t.polarity === null ? "" : String(t.polarity));
  return (
    <li>
      <form
        className="flex flex-wrap items-center gap-2 py-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate({ method: "PATCH", url: base, body: { term: t.term, meaning, polarity } });
        }}
      >
        <span className="w-20 shrink-0 font-medium">{t.term}</span>
        <input
          className={`${field} h-7 min-w-0 flex-1 basis-48`}
          aria-label={`${t.term} 的意思`}
          maxLength={100}
          value={meaning}
          onChange={(e) => setMeaning(e.target.value)}
        />
        <select className={`${field} h-7`} aria-label="方向" value={polarity} onChange={(e) => setPolarity(e.target.value)}>
          {Object.entries(POLARITY).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        {changed ? (
          <Button type="submit" size="xs" disabled={action.isPending}>
            儲存
          </Button>
        ) : null}
        <Button
          type="button"
          size="xs"
          variant="ghost"
          className="text-destructive"
          disabled={action.isPending}
          onClick={() => action.mutate({ method: "DELETE", url: base })}
        >
          刪除
        </Button>
        <ErrorText error={action.error} />
      </form>
    </li>
  );
}

/** Other names of stocks for linking news (護國神山 → 2330). */
export function AliasEditor({ aliases }: { aliases: AliasRow[] }) {
  const action = useSend();
  const [alias, setAlias] = useState("");
  const [symbol, setSymbol] = useState("");
  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate(
            { method: "POST", url: "/api/admin/aliases", body: { alias, symbol } },
            {
              onSuccess: () => {
                setAlias("");
                setSymbol("");
              },
            },
          );
        }}
      >
        <input className={`${field} w-32`} placeholder="別名" aria-label="別名" maxLength={20} value={alias} onChange={(e) => setAlias(e.target.value)} />
        <input className={`${field} w-24`} placeholder="代號" aria-label="代號" maxLength={6} value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        <Button type="submit" size="sm" disabled={alias.trim().length < 2 || !symbol.trim() || action.isPending}>
          新增
        </Button>
        <ErrorText error={action.error} />
      </form>
      {aliases.length === 0 ? (
        <p className="text-sm text-muted-foreground">還沒有別名。</p>
      ) : (
        <ul className="flex flex-wrap gap-2 text-sm">
          {aliases.map((a) => (
            <li key={a.alias} className="flex items-center gap-1 rounded-md border py-0.5 pr-0.5 pl-2">
              <span>{a.alias}</span>
              <span className="text-xs text-muted-foreground">
                → <span className="font-semibold tabular-nums">{a.symbol}</span> {a.name}
              </span>
              <Button
                size="xs"
                variant="ghost"
                aria-label={`刪除別名 ${a.alias}`}
                disabled={action.isPending}
                onClick={() => action.mutate({ method: "DELETE", url: `/api/admin/aliases/${encodeURIComponent(a.alias)}` })}
              >
                ×
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- settings -------------------------------------------------------------------------

const SETTING_FIELDS: { key: keyof NewsSettings; label: string; hint: string; step: string }[] = [
  { key: "sentimentAlert", label: "新聞情緒門檻", hint: "|情緒| 達此值（0.3～1）", step: "0.05" },
  { key: "importanceAlert", label: "重要度門檻", hint: "1～5，同產業、題材再加 1", step: "1" },
  { key: "buzzSigma", label: "社群熱度倍數", hint: "平均加幾個標準差", step: "0.5" },
  { key: "buzzMinPosts", label: "社群熱度最少篇數", hint: "當天至少幾篇", step: "1" },
  { key: "llmDailyItems", label: "每日 AI 分析上限", hint: "則（0 = 暫停）", step: "10" },
  { key: "llmDailyUsdCap", label: "付費服務每日上限", hint: "美元（0 = 不用付費服務）", step: "0.1" },
];

/** Alert thresholds and LLM caps (settings key news, D-145). */
export function NewsSettingsForm({ settings }: { settings: NewsSettings }) {
  const save = useSend();
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(settings).map(([k, v]) => [k, String(v)])),
  );
  const changed = SETTING_FIELDS.some((f) => values[f.key] !== String(settings[f.key]));
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({
          method: "PUT",
          url: "/api/settings/news",
          body: Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Number(v)])),
        });
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {SETTING_FIELDS.map((f) => (
          <label key={f.key} className="space-y-1 text-sm">
            <span className="block font-medium">{f.label}</span>
            <input
              className={`${field} w-full`}
              type="number"
              step={f.step}
              value={values[f.key]}
              onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
            />
            <span className="block text-xs text-muted-foreground">{f.hint}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={!changed || save.isPending}>
          儲存設定
        </Button>
        <ErrorText error={save.error} />
      </div>
    </form>
  );
}
