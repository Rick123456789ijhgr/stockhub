import Link from "next/link";

import { FlowRanking } from "@/components/chips/flow-ranking";
import { IndexOverview } from "@/components/market/index-overview";
import { MarketStrip } from "@/components/market/market-strip";
import { HomeNews } from "@/components/news/home-news";
import { Section } from "@/components/section";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";

/**
 * Home = the Taiwan market (D-134): the index chart, institutional flows and the important
 * news of the last two days (M6), then the international markets as context. The industry and theme heatmap is a tab of /stocks;
 * holdings and alerts are on /portfolio; the international markets and macro in full on
 * /market. No page title (D-126): the session rail says when the numbers are from.
 */
export default function HomePage() {
  return (
    <>
      <h1 className="sr-only">台股總覽</h1>
      <HomeContent />
    </>
  );
}

async function HomeContent() {
  await requireUser();
  const db = getDb();
  return (
    <div className="space-y-10">
      <Section title="大盤走勢">
        <IndexOverview db={db} />
      </Section>
      <Section title="三大法人買賣超">
        <FlowRanking db={db} />
      </Section>
      <Section
        title="重要新聞"
        actions={
          <Link href="/news" className="underline-offset-4 hover:text-foreground hover:underline">
            全部新聞
          </Link>
        }
      >
        <HomeNews db={db} />
      </Section>
      <Section
        title="國際市場"
        actions={
          <Link href="/market" className="underline-offset-4 hover:text-foreground hover:underline">
            全部國際市場
          </Link>
        }
      >
        <MarketStrip db={db} today={taipeiToday()} />
      </Section>
    </div>
  );
}
