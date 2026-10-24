import type { Kysely } from "kysely";

import { NewsList } from "@/components/news/news-list";
import type { DB } from "@/lib/db";
import { hoursAgo, listNews } from "@/lib/news";

const WINDOW_HOURS = 48;

/** Home: the last two days' important items (importance 4 or 5), news and announcements. */
export async function HomeNews({ db }: { db: Kysely<DB> }) {
  const since = hoursAgo(WINDOW_HOURS);
  const items = (await listNews(db, { minImportance: 4, since, limit: 40 })).filter(
    (i) => i.channel !== "social",
  );
  return (
    <NewsList
      items={items}
      now={new Date()}
      showChannel
      initial={6}
      empty="近兩天沒有 AI 評為重要的新聞或重大訊息。"
    />
  );
}
