import Link from "next/link";

import { FlowRanking } from "@/components/chips/flow-ranking";
import { type IndexCode, IndexOverview, parseIndexCode } from "@/components/market/index-overview";
import { MarketStrip } from "@/components/market/market-strip";
import { Section } from "@/components/section";
import { SegmentedLinks } from "@/components/segmented-links";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";

const INDEX_LABEL: Record<IndexCode, string> = { TAIEX: "加權", TPEX: "櫃買" };

/**
 * Home = the Taiwan market (D-134): the index chart and institutional flows, then the
 * international markets as context. The industry and theme heatmap is a tab of /stocks;
 * holdings and alerts are on /portfolio; the international markets and macro in full on
 * /market. No page title (D-126): the session rail says when the numbers are from.
 */
export default function HomePage({ searchParams }: PageProps<"/">) {
  return (
    <>
      <h1 className="sr-only">台股總覽</h1>
      <HomeContent searchParams={searchParams} />
    </>
  );
}

async function HomeContent({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  await requireUser();
  const code = parseIndexCode((await searchParams).index);
  const db = getDb();
  return (
    <div className="space-y-10">
      <Section
        title="大盤走勢"
        actions={
          <SegmentedLinks
            label="指數"
            options={INDEX_LABEL}
            active={code}
            href={(c) => (c === "TAIEX" ? "/" : `/?index=${c}`)}
          />
        }
      >
        <IndexOverview db={db} code={code} />
      </Section>
      <Section title="三大法人買賣超">
        <FlowRanking db={db} />
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
