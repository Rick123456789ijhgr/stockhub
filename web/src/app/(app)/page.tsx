import Link from "next/link";

import { FlowRanking } from "@/components/chips/flow-ranking";
import { type HeatmapBy, HeatmapSection, parseHeatmapParams } from "@/components/market/heatmap-section";
import {
  INDEX_RANGE_LABEL,
  IndexOverview,
  type IndexRange,
  parseIndexRange,
} from "@/components/market/index-overview";
import { MarketStrip } from "@/components/market/market-strip";
import { Section } from "@/components/section";
import { SegmentedLinks } from "@/components/segmented-links";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import type { HeatmapPeriod } from "@/lib/heatmap-data";
import { taipeiToday } from "@/lib/market-hours";

type HomeState = { range: IndexRange; by: HeatmapBy; period: HeatmapPeriod };

/** The home URL for `state`, leaving out the defaults. */
function homeHref({ range, by, period }: HomeState): string {
  const params = new URLSearchParams();
  if (range !== "6m") params.set("range", range);
  if (by !== "industry") params.set("by", by);
  if (period !== "1d") params.set("period", period);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

/**
 * Home = the Taiwan market (D-134): the indexes, institutional flows and the industry and
 * theme heatmap, then the international markets as context. Holdings and alerts are on
 * /portfolio; the international markets and macro in full on /market. No page title
 * (D-126): the session rail says when the numbers are from.
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
  const query = await searchParams;
  const state: HomeState = { range: parseIndexRange(query.range), ...parseHeatmapParams(query) };
  const db = getDb();
  const today = taipeiToday();
  return (
    <div className="space-y-10">
      <Section
        title="大盤走勢"
        actions={
          <SegmentedLinks
            label="期間"
            options={INDEX_RANGE_LABEL}
            active={state.range}
            href={(range) => homeHref({ ...state, range })}
          />
        }
      >
        <IndexOverview db={db} today={today} range={state.range} />
      </Section>
      <Section title="三大法人買賣超">
        <FlowRanking db={db} />
      </Section>
      <div id="heatmap" className="scroll-mt-4">
        <Section title="產業與題材熱力圖">
          <HeatmapSection
            db={db}
            by={state.by}
            period={state.period}
            href={(by, period) => homeHref({ ...state, by, period })}
          />
        </Section>
      </div>
      <Section
        title="國際市場"
        actions={
          <Link href="/market" className="underline-offset-4 hover:text-foreground hover:underline">
            全部國際市場
          </Link>
        }
      >
        <MarketStrip db={db} today={today} />
      </Section>
    </div>
  );
}
