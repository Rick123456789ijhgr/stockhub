import { Search } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/coming-soon";
import { activeTab, type PageTab, PageTabs, tabHref } from "@/components/page-tabs";
import { ToggleLinks } from "@/components/segmented-links";
import { StockList } from "@/components/stocks/stock-list";
import { Card, CardContent } from "@/components/ui/card";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import {
  getRanking,
  type Ranking,
  type RankingKind,
  searchStocks,
  type StockListItem,
} from "@/lib/stocks";

export const metadata: Metadata = { title: "個股" };

export default function StocksPage({ searchParams }: PageProps<"/stocks">) {
  return (
    <>
      <PageHeader title="個股" description="最新交易日的熱門榜單；輸入代號或名稱搜尋上市、上櫃股票與 ETF（搜尋時也會列出已下市的公司）。" />
      <StockSearch searchParams={searchParams} />
    </>
  );
}

async function StockSearch({ searchParams }: { searchParams: PageProps<"/stocks">["searchParams"] }) {
  await requireUser();
  const params = await searchParams;
  const q = (Array.isArray(params.q) ? params.q[0] : params.q)?.trim() ?? "";
  const kind: RankingKind = params.type === "etf" || params.type === "all" ? params.type : "stock";
  const tab = activeTab(kind === "etf" ? ETF_RANKING_TABS : RANKING_TABS, params.tab);

  return (
    <>
      <form action="/stocks" className="mb-4 flex gap-2" role="search">
        <label className="relative flex-1">
          <span className="sr-only">代號或名稱</span>
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            name="q"
            defaultValue={q}
            placeholder="例如 2330、台積電、0050"
            inputMode="search"
            autoComplete="off"
            className="h-10 w-full rounded-lg border bg-background pr-3 pl-9 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
          />
        </label>
        <button
          type="submit"
          className="h-10 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
        >
          搜尋
        </button>
      </form>

      {q ? <SearchResults q={q} /> : <RankingView kind={kind} ranking={tab} />}
    </>
  );
}

const RANKING_TABS: PageTab<Ranking>[] = [
  { key: "turnover", label: "成交金額" },
  { key: "volume", label: "成交量" },
  { key: "gainers", label: "漲幅" },
  { key: "losers", label: "跌幅" },
  { key: "marketCap", label: "市值" },
];
/** ETFs have no market value (their units are not shares of a company). */
const ETF_RANKING_TABS = RANKING_TABS.filter((t) => t.key !== "marketCap");

type Listing = "stock" | "etf";
const LISTING_LABEL: Record<Listing, string> = { stock: "股票", etf: "ETF" };
const KIND_LABEL: Record<RankingKind, string> = { stock: "股票", etf: "ETF", all: "股票與 ETF" };
const KIND_LISTINGS: Record<RankingKind, Listing[]> = {
  stock: ["stock"],
  etf: ["etf"],
  all: ["stock", "etf"],
};

/** The kind with `listing` switched on or off; null when it is the only one left on. */
function toggledKind(kind: RankingKind, listing: Listing): RankingKind | null {
  const on = KIND_LISTINGS[kind];
  const next = on.includes(listing) ? on.filter((l) => l !== listing) : [...on, listing];
  if (next.length === 0) return null;
  return next.length === 2 ? "all" : next[0]!;
}

const RANKING_NOTE: Record<Ranking, string> = {
  turnover: "成交金額前 50 名，最能看出當天的熱門標的。",
  volume: "成交量前 50 名；低價的張數容易偏多。",
  gainers: "漲幅前 50 名，以參考價（還原後的前收）計算。",
  losers: "跌幅前 50 名，以參考價（還原後的前收）計算。",
  marketCap: "市值前 50 名＝收盤價 × 發行股數。",
};

/** Query that keeps the kind when switching ranking tabs (stocks are the default). */
const kindQuery = (kind: RankingKind): Record<string, string> =>
  kind === "stock" ? {} : { type: kind };

async function RankingView({ kind, ranking }: { kind: RankingKind; ranking: Ranking }) {
  const { date, rows } = await getRanking(getDb(), ranking, kind);
  const tabs = kind === "etf" ? ETF_RANKING_TABS : RANKING_TABS;
  return (
    <div className="space-y-3">
      <PageTabs
        tabs={tabs}
        active={ranking}
        basePath="/stocks"
        query={kindQuery(kind)}
        end={
          <ToggleLinks
            label="類別"
            options={LISTING_LABEL}
            selected={KIND_LISTINGS[kind]}
            // Keep the ranking across kinds when the new kind has it.
            href={(listing) => {
              const next = toggledKind(kind, listing);
              if (next === null) return null;
              const keep = (next === "etf" ? ETF_RANKING_TABS : RANKING_TABS).some(
                (t) => t.key === ranking,
              );
              return tabHref("/stocks", ranking, !keep || ranking === RANKING_TABS[0]!.key, kindQuery(next));
            }}
          />
        }
      />
      {rows.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            還沒有日線資料，請先執行 make etl-daily。
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {date} 收盤，{ranking === "marketCap" ? "股票" : KIND_LABEL[kind]}
            {/* A space between Latin and CJK: "ETF 成交金額", "股票成交金額". */}
            {ranking !== "marketCap" && kind !== "stock" ? " " : ""}
            {RANKING_NOTE[ranking]}
            {ranking === "marketCap" && kind === "all" ? "ETF 沒有市值，不列入。" : ""}
          </p>
          <StockList stocks={rows} ranking={ranking} etf={kind === "etf"} />
        </>
      )}
    </div>
  );
}

async function SearchResults({ q }: { q: string }) {
  const found = await searchStocks(getDb(), q);
  if (found.length === 0) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">找不到「{q}」。</CardContent>
      </Card>
    );
  }
  // The group holding the best match comes first (searching 50 finds 0050 before 5013).
  const groups: [string, StockListItem[]][] = (
    [
      ["股票", found.filter((s) => s.type === "stock")],
      ["ETF", found.filter((s) => s.type === "etf")],
    ] satisfies [string, StockListItem[]][]
  ).sort(([, a], [, b]) => found.indexOf(a[0]!) - found.indexOf(b[0]!));
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        「{q}」的搜尋結果：代號或名稱含「{q}」，最接近、成交最多的在前（最多 100 筆）·{" "}
        <Link href="/stocks" className="hover:text-foreground hover:underline">
          回到榜單
        </Link>
      </p>
      {groups.map(([label, rows]) =>
        rows.length ? (
          <section key={label} aria-label={label} className="space-y-2">
            <h2 className="text-sm font-medium">
              {label}
              <span className="ml-1.5 text-muted-foreground tabular-nums">{rows.length}</span>
            </h2>
            <StockList stocks={rows} etf={label === "ETF"} />
          </section>
        ) : null,
      )}
    </div>
  );
}
