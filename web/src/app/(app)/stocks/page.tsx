import { Search } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/coming-soon";
import { activeTab, type PageTab, PageTabs } from "@/components/page-tabs";
import { StockList } from "@/components/stocks/stock-list";
import { Card, CardContent } from "@/components/ui/card";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { getRanking, type Ranking, searchStocks } from "@/lib/stocks";

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
  const tab = activeTab(RANKING_TABS, params.tab);

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

      {q ? <SearchResults q={q} /> : <RankingView ranking={tab} />}
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

const RANKING_NOTE: Record<Ranking, string> = {
  turnover: "成交金額前 50 名（含 ETF），最能看出當天的熱門股。",
  volume: "成交量前 50 名（含 ETF）；低價股的張數容易偏多。",
  gainers: "漲幅前 50 名（不含 ETF），以參考價（還原後的前收）計算。",
  losers: "跌幅前 50 名（不含 ETF），以參考價（還原後的前收）計算。",
  marketCap: "市值前 50 名（不含 ETF）＝收盤價 × 發行股數。",
};

async function RankingView({ ranking }: { ranking: Ranking }) {
  const { date, rows } = await getRanking(getDb(), ranking);
  return (
    <div className="space-y-3">
      <PageTabs tabs={RANKING_TABS} active={ranking} basePath="/stocks" />
      {rows.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            還沒有日線資料，請先執行 make etl-daily。
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {date} 收盤 · {RANKING_NOTE[ranking]}
          </p>
          <StockList stocks={rows} ranking={ranking} />
        </>
      )}
    </div>
  );
}

async function SearchResults({ q }: { q: string }) {
  const stocks = await searchStocks(getDb(), q);
  if (stocks.length === 0) {
    return (
      <Card>
        <CardContent className="text-sm text-muted-foreground">找不到「{q}」。</CardContent>
      </Card>
    );
  }
  return (
    <>
      <p className="mb-2 text-xs text-muted-foreground">
        「{q}」的搜尋結果（最多顯示 100 筆）·{" "}
        <Link href="/stocks" className="hover:text-foreground hover:underline">
          回到榜單
        </Link>
      </p>
      <StockList stocks={stocks} />
    </>
  );
}
