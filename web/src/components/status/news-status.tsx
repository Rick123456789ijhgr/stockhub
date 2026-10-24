import Link from "next/link";

import { JobButton } from "@/components/jobs/job-button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatInteger, formatTaipeiDateTime } from "@/lib/format";
import type { NewsCoverage } from "@/lib/news";
import type { LlmRow } from "@/lib/news-admin";

/** News, announcements and posts: how many, how fresh, and the LLM services' state today. */
export function NewsStatusCard({ coverage, services }: { coverage: NewsCoverage; services: LlmRow[] }) {
  const usable = services.filter((s) => s.enabled && s.keySet);
  const requests = services.reduce((sum, s) => sum + s.today.requests, 0);
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-sm">新聞與 AI</CardTitle>
        <CardDescription>每天 07:00～23:00 每分鐘一輪：抓到期的來源、送 AI 分析、檢查警示；每日更新再彙整情緒。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 tabular-nums">
          <dt className="text-muted-foreground">項目</dt>
          <dd>
            {formatInteger(coverage.items)} 則
            {coverage.firstItem ? `（自 ${formatTaipeiDateTime(coverage.firstItem).slice(0, 10)}）` : ""}
          </dd>
          <dt className="text-muted-foreground">最後抓取</dt>
          <dd>{formatTaipeiDateTime(coverage.lastFetch)}</dd>
          <dt className="text-muted-foreground">等待 AI</dt>
          <dd>{formatInteger(coverage.pending)} 則</dd>
          <dt className="text-muted-foreground">AI 服務</dt>
          <dd>
            可用 {usable.length} / {services.length} 個，今日 {formatInteger(requests)} 次請求
          </dd>
        </dl>
        {usable.length === 0 ? (
          <p>
            還沒有可用的 LLM 服務：在 .env 加上金鑰（GEMINI_API_KEY 等），新聞會照常收集，只是沒有摘要與情緒。
          </p>
        ) : null}
        {coverage.sourcesWithErrors > 0 ? (
          <p>
            {coverage.sourcesWithErrors} 個來源最近一次抓取失敗，
            <Link href="/admin?tab=news" className="underline underline-offset-4">
              到設定頁查看
            </Link>
            。
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <JobButton size="xs" variant="outline" label="立即更新新聞" requests={[{ job: "sync_news", params: { force: "true" } }]} />
          <JobButton size="xs" variant="outline" label="檢查 AI 服務" requests={[{ job: "check_llm_providers" }]} />
        </div>
      </CardContent>
    </Card>
  );
}
