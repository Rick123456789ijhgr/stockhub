import type { Metadata } from "next";

import { PageHeader } from "@/components/coming-soon";
import { InfoNote } from "@/components/disclosure";
import { JobButton } from "@/components/jobs/job-button";
import { NewsList } from "@/components/news/news-list";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { SegmentedLinks } from "@/components/segmented-links";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { formatTaipeiDateTime } from "@/lib/format";
import { listNews, newsCoverage, type NewsQuery, watchedStockIds } from "@/lib/news";

export const metadata: Metadata = { title: "新聞" };

type Tab = "all" | "watched" | "announcement" | "social";
const TABS: PageTab<Tab>[] = [
  { key: "all", label: "全部" },
  { key: "watched", label: "持股與自選" },
  { key: "announcement", label: "重大訊息" },
  { key: "social", label: "社群" },
];
type Level = "all" | "important";
const LEVELS: Record<Level, string> = { all: "全部", important: "重要（4 分以上）" };

const EMPTY: Record<Tab, string> = {
  all: "還沒有新聞。排程每天 07:00～23:00 每分鐘檢查一次來源，也可以按「立即更新」。",
  watched: "持股與自選股最近沒有相關的新聞或公告。",
  announcement: "最近沒有重大訊息。",
  social: "還沒有論壇貼文。",
};

export default function NewsPage({ searchParams }: PageProps<"/news">) {
  return (
    <>
      <PageHeader
        title="新聞"
        description="新聞、重大訊息與論壇貼文；摘要與情緒由 AI 產生，僅供參考。"
        actions={
          <JobButton
            requests={[{ job: "sync_news", params: { force: "true" } }]}
            label="立即更新"
          />
        }
      />
      <NewsContent searchParams={searchParams} />
    </>
  );
}

async function NewsContent({ searchParams }: { searchParams: PageProps<"/news">["searchParams"] }) {
  await requireUser();
  const db = getDb();
  const query = await searchParams;
  const tab = activeTab(TABS, query.tab);
  const level: Level = query.level === "important" ? "important" : "all";
  const filter: NewsQuery = { limit: 200, minImportance: level === "important" ? 4 : undefined };
  if (tab === "watched") filter.stockIds = await watchedStockIds(db);
  if (tab === "announcement") filter.channel = "announcement";
  if (tab === "social") filter.channel = "social";
  const [items, coverage] = await Promise.all([listNews(db, filter), newsCoverage(db)]);
  const href = (key: Level) => {
    const params = new URLSearchParams();
    if (tab !== "all") params.set("tab", tab);
    if (key !== "all") params.set("level", key);
    const search = params.toString();
    return search ? `/news?${search}` : "/news";
  };

  return (
    <div className="space-y-4">
      <PageTabs
        tabs={TABS}
        active={tab}
        basePath="/news"
        query={level === "important" ? { level } : undefined}
        end={<SegmentedLinks options={LEVELS} active={level} href={href} label="重要度" />}
      />
      <InfoNote>
        同一事件的多篇報導只列第一篇（標示「另有 N 則相同報導」）；摘要、情緒與重要度由免費的
        LLM 服務產生，滑過「AI 摘要」可看是哪個模型。論壇貼文標示作者自己的看多或看空時，直接採用作者的標示。
        最後抓取 {formatTaipeiDateTime(coverage.lastFetch)}，等待 AI 處理 {coverage.pending} 則
        {coverage.sourcesWithErrors > 0 ? `，${coverage.sourcesWithErrors} 個來源最近一次抓取失敗（見設定）` : ""}。
      </InfoNote>
      <NewsList
        items={items}
        now={new Date()}
        showChannel={tab === "all" || tab === "watched"}
        initial={20}
        empty={EMPTY[tab]}
      />
    </div>
  );
}
