import type { Metadata } from "next";

import { PageHeader } from "@/components/coming-soon";
import { HeatmapSection, parseHeatmapParams } from "@/components/market/heatmap-section";
import { MacroSection } from "@/components/market/macro-section";
import { MarketOverview } from "@/components/market/market-overview";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";

export const metadata: Metadata = { title: "市場" };

type Tab = "overview" | "heatmap" | "macro";
const TABS: PageTab<Tab>[] = [
  { key: "overview", label: "大盤與國際" },
  { key: "heatmap", label: "熱力圖" },
  { key: "macro", label: "總經" },
];

export default function MarketPage({ searchParams }: PageProps<"/market">) {
  return (
    <>
      <PageHeader title="市場" description="台股與國際市場、產業與題材熱力圖、總經指標與事件。" />
      <MarketContent searchParams={searchParams} />
    </>
  );
}

async function MarketContent({ searchParams }: { searchParams: PageProps<"/market">["searchParams"] }) {
  await requireUser();
  const query = await searchParams;
  const tab = activeTab(TABS, query.tab);
  const db = getDb();
  const today = taipeiToday();
  return (
    <div className="space-y-4">
      <PageTabs tabs={TABS} active={tab} basePath="/market" />
      {tab === "overview" ? <MarketOverview db={db} today={today} /> : null}
      {tab === "heatmap" ? <HeatmapSection db={db} {...parseHeatmapParams(query)} /> : null}
      {tab === "macro" ? <MacroSection db={db} today={today} /> : null}
    </div>
  );
}
