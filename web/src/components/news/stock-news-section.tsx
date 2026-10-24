import type { Kysely } from "kysely";

import { TimeChart } from "@/components/charts/time-chart";
import { InfoNote } from "@/components/disclosure";
import { NewsList } from "@/components/news/news-list";
import { Section } from "@/components/section";
import { Card, CardContent } from "@/components/ui/card";
import type { DB } from "@/lib/db";
import { listNews, stockSentiment } from "@/lib/news";
import type { StockDetail } from "@/lib/stocks";

/**
 * A stock's news tab: daily sentiment (news and all sources) with the item counts, then its
 * news and announcements, then forum posts. Sentiment accumulates from the M6 launch on.
 */
export async function StockNewsSection({ db, stock }: { db: Kysely<DB>; stock: StockDetail }) {
  const id = String(stock.id);
  const [points, news, posts] = await Promise.all([
    stockSentiment(db, id),
    listNews(db, { stockIds: [id], limit: 80 }).then((items) =>
      items.filter((i) => i.channel !== "social"),
    ),
    listNews(db, { stockIds: [id], channel: "social", limit: 40 }),
  ]);
  const now = new Date();
  const all = points.filter((p) => p.scope === "all");
  const byScope = (scope: string) =>
    points.filter((p) => p.scope === scope).map((p) => ({ time: p.tradeDate, value: p.sentiment }));

  return (
    <div className="space-y-8">
      <Section title="每日情緒">
        {all.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            還沒有情緒資料。每天收盤後彙整前一段時間的新聞與貼文，從新聞功能上線日開始累積。
          </p>
        ) : (
          <Card size="sm">
            <CardContent className="space-y-4">
              <TimeChart
                label="每日情緒"
                format="score"
                height={200}
                series={[
                  { name: "全部", kind: "line", color: "--series-1", data: byScope("all") },
                  { name: "新聞", kind: "line", color: "--series-2", data: byScope("news") },
                ]}
              />
              <TimeChart
                label="每日則數"
                format="count"
                height={120}
                series={[
                  {
                    name: "則數",
                    kind: "histogram",
                    color: "--muted-foreground",
                    data: all.map((p) => ({ time: p.tradeDate, value: p.items })),
                  },
                ]}
              />
            </CardContent>
          </Card>
        )}
        <InfoNote>
          情緒介於 −1（非常負面）與 +1（非常正面），每則以關聯權重乘重要度加權平均；收盤（13:30）後與假日的新聞算在下一個交易日。
          同產業、同題材的新聞權重較低。論壇貼文標示了作者看多或看空時，直接採用作者的標示（±0.8）。
        </InfoNote>
      </Section>
      <Section title="新聞與重大訊息">
        <NewsList
          items={news}
          now={now}
          showChannel
          current={stock.symbol}
          empty="最近沒有關於這檔的新聞或重大訊息。"
        />
      </Section>
      <Section title="社群">
        <NewsList
          items={posts}
          now={now}
          current={stock.symbol}
          initial={10}
          empty="最近沒有關於這檔的論壇貼文（PTT 只抓 [標的] 文，同學會只抓熱門貼文）。"
        />
      </Section>
    </div>
  );
}
