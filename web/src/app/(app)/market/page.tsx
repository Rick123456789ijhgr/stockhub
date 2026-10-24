import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/coming-soon";
import { MacroSection } from "@/components/market/macro-section";
import { MarketOverview } from "@/components/market/market-overview";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { taipeiToday } from "@/lib/market-hours";

export const metadata: Metadata = { title: "國際市場" };

type Tab = "overview" | "macro";
const TABS: PageTab<Tab>[] = [
  { key: "overview", label: "國際市場" },
  { key: "macro", label: "總經" },
];

/** International markets and macro; Taiwan's indexes and flows are on the home page (D-134). */
export default function MarketPage({ searchParams }: PageProps<"/market">) {
  return (
    <>
      <PageHeader title="國際市場" description="國際股市、匯率、商品與利率，以及台美總經指標與事件。台股大盤與法人在首頁，熱力圖在個股頁。" />
      <MarketContent searchParams={searchParams} />
    </>
  );
}

async function MarketContent({ searchParams }: { searchParams: PageProps<"/market">["searchParams"] }) {
  await requireUser();
  const query = await searchParams;
  // The heatmap moved to a tab of /stocks; old links and bookmarks follow it.
  if (query.tab === "heatmap") {
    const params = new URLSearchParams({ tab: "heatmap" });
    for (const key of ["by", "period"]) {
      const value = query[key];
      if (typeof value === "string") params.set(key, value);
    }
    redirect(`/stocks?${params}`);
  }
  const tab = activeTab(TABS, query.tab);
  const db = getDb();
  const today = taipeiToday();
  return (
    <div className="space-y-4">
      <PageTabs tabs={TABS} active={tab} basePath="/market" />
      {tab === "overview" ? <MarketOverview db={db} today={today} /> : null}
      {tab === "macro" ? <MacroSection db={db} today={today} /> : null}
    </div>
  );
}
