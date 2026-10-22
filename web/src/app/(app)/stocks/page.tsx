import { Search } from "lucide-react";
import type { Metadata } from "next";

import { PageHeader } from "@/components/coming-soon";
import { StockList } from "@/components/stocks/stock-list";
import { Card, CardContent } from "@/components/ui/card";
import { requireUser } from "@/lib/auth/session";
import { getDb } from "@/lib/db";
import { searchStocks } from "@/lib/stocks";

export const metadata: Metadata = { title: "個股" };

export default function StocksPage({ searchParams }: PageProps<"/stocks">) {
  return (
    <>
      <PageHeader title="個股" description="輸入代號或名稱搜尋上市、上櫃股票與 ETF（搜尋時也會列出已下市的公司）。" />
      <StockSearch searchParams={searchParams} />
    </>
  );
}

async function StockSearch({ searchParams }: { searchParams: PageProps<"/stocks">["searchParams"] }) {
  await requireUser();
  const params = await searchParams;
  const q = (Array.isArray(params.q) ? params.q[0] : params.q)?.trim() ?? "";
  const stocks = await searchStocks(getDb(), q);

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

      {stocks.length === 0 ? (
        <Card>
          <CardContent className="text-sm text-muted-foreground">
            {q ? `找不到「${q}」。` : "股票主檔是空的，請先執行 make etl-daily。"}
          </CardContent>
        </Card>
      ) : (
        <>
          <p className="mb-2 text-xs text-muted-foreground">
            {q ? `「${q}」的搜尋結果` : "全部"}（最多顯示 100 筆）
          </p>
          <StockList stocks={stocks} />
        </>
      )}
    </>
  );
}
